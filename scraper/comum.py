"""Utilidades compartilhadas: HTTP, normalização de texto, classificação de vagas de T.I.
e identificação de estados do Nordeste."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import requests

log = logging.getLogger("vagas")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 VagasTI-Nordeste/1.0"
)

# --------------------------------------------------------------------------------------
# Estados do Nordeste
# --------------------------------------------------------------------------------------

ESTADOS_NE = {
    "AL": "Alagoas",
    "BA": "Bahia",
    "CE": "Ceará",
    "MA": "Maranhão",
    "PB": "Paraíba",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RN": "Rio Grande do Norte",
    "SE": "Sergipe",
}

# Capitais e cidades relevantes, usadas quando a fonte informa só a cidade.
CIDADES_NE = {
    "fortaleza": "CE", "caucaia": "CE", "maracanau": "CE", "juazeiro do norte": "CE",
    "sobral": "CE", "crato": "CE", "eusebio": "CE", "aquiraz": "CE", "itapipoca": "CE",
    "maranguape": "CE", "horizonte": "CE", "pacatuba": "CE", "quixada": "CE",
    "iguatu": "CE", "russas": "CE", "limoeiro do norte": "CE", "aracati": "CE",
    "recife": "PE", "jaboatao dos guararapes": "PE", "olinda": "PE", "caruaru": "PE",
    "petrolina": "PE", "paulista": "PE", "cabo de santo agostinho": "PE",
    "salvador": "BA", "feira de santana": "BA", "vitoria da conquista": "BA",
    "camacari": "BA", "lauro de freitas": "BA", "ilheus": "BA", "itabuna": "BA",
    "sao luis": "MA", "imperatriz": "MA",
    "teresina": "PI", "parnaiba": "PI",
    "natal": "RN", "mossoro": "RN", "parnamirim": "RN",
    "joao pessoa": "PB", "campina grande": "PB",
    "maceio": "AL", "arapiraca": "AL",
    "aracaju": "SE", "nossa senhora do socorro": "SE",
}

_NOME_PARA_UF = {}
for _uf, _nome in ESTADOS_NE.items():
    _NOME_PARA_UF[_uf.lower()] = _uf


def sem_acento(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


for _uf, _nome in ESTADOS_NE.items():
    _NOME_PARA_UF[sem_acento(_nome)] = _uf


def uf_de(estado: str | None) -> str | None:
    """Converte 'Ceará', 'ceara', 'CE' etc. em UF do Nordeste (ou None)."""
    if not estado:
        return None
    return _NOME_PARA_UF.get(sem_acento(estado))


def extrair_local(texto: str | None) -> tuple[str | None, str | None]:
    """Extrai (cidade, UF) de textos como 'Fortaleza / CE', 'Recife - PE',
    'Salvador, Bahia', 'Teresina'. Retorna UF somente se for do Nordeste."""
    if not texto:
        return None, None
    bruto = re.sub(r"\s+", " ", texto).strip()
    partes = [p.strip() for p in re.split(r"[/,\-–|()]", bruto) if p.strip()]
    uf = None
    cidade = None
    for parte in reversed(partes):
        achou = uf_de(parte)
        if achou:
            uf = achou
            break
    for parte in partes:
        if not uf_de(parte) and sem_acento(parte) not in ("brasil", "br", "remoto", "home office"):
            cidade = parte
            break
    if not uf and cidade:
        uf = CIDADES_NE.get(sem_acento(cidade))
    if not uf:
        # Busca por qualquer cidade conhecida no texto inteiro
        norm = sem_acento(bruto)
        for nome_cidade, sigla in CIDADES_NE.items():
            if re.search(rf"\b{re.escape(nome_cidade)}\b", norm):
                return nome_cidade.title(), sigla
    return cidade, uf


# --------------------------------------------------------------------------------------
# Classificação de vagas de T.I.
# --------------------------------------------------------------------------------------

# (categoria, padrões regex aplicados ao título normalizado sem acentos)
CATEGORIAS_TI: list[tuple[str, list[str]]] = [
    ("Segurança da Informação", [
        r"seguranca da informacao", r"seguranca cibernetica", r"ciberseguranca",
        r"cyber ?security", r"\bsoc\b", r"pentest", r"\bappsec\b", r"\bsecops\b",
    ]),
    ("Dados & IA", [
        r"cientista de dados", r"ciencia de dados", r"engenheir[oa] de dados",
        r"analista de dados", r"arquitet[oa] de dados", r"\bdata\b", r"\bbi\b",
        r"business intelligence", r"power ?bi", r"machine learning", r"\bml\b",
        r"inteligencia artificial", r"\bia\b", r"\bai\b", r"\bllm\b", r"\bdba\b",
        r"banco de dados", r"analytics", r"\betl\b",
    ]),
    ("Infraestrutura & Cloud", [
        r"devops", r"\bsre\b", r"cloud", r"\baws\b", r"\bazure\b", r"\bgcp\b",
        r"infraestrutura (de )?(ti|redes|cloud|tecnologia)", r"analista de infraestrutura",
        r"tecnico de infraestrutura", r"analista de redes", r"tecnico de redes",
        r"administrador de redes", r"redes de computadores", r"telecom", r"\bnoc\b",
        r"sysadmin", r"administrador de sistemas", r"linux",
    ]),
    ("QA & Testes", [
        r"\bqa\b", r"quality assurance", r"analista de testes?", r"testador",
        r"automacao de testes", r"\btester\b", r"qualidade de software",
    ]),
    ("UX/UI & Design Digital", [
        r"\bux\b", r"\bui\b", r"product designer", r"designer de produto",
        r"designer de interface", r"ux writer",
    ]),
    ("Produto & Agilidade", [
        r"product owner", r"\bpo\b", r"product manager", r"gerente de produto",
        r"scrum master", r"agile coach", r"agilista", r"analista de requisitos",
        r"analista de negocios de ti",
    ]),
    ("ERP & Sistemas Corporativos", [
        r"\bsap\b", r"\berp\b", r"\btotvs\b", r"protheus", r"\bcrm\b", r"salesforce",
        r"oracle", r"dynamics",
    ]),
    ("Suporte & Service Desk", [
        r"suporte tecnico", r"suporte de ti", r"suporte (em|a) (ti|sistemas|informatica)",
        r"analista de suporte", r"tecnico de suporte", r"help ?desk", r"service ?desk",
        r"tecnico de informatica", r"tecnico em informatica", r"suporte n[123]",
        r"atendimento (de|em) ti", r"field service",
    ]),
    ("Desenvolvimento", [
        r"desenvolvedor", r"desenvolvedora", r"developer", r"\bdev\b", r"programador",
        r"programadora", r"engenheir[oa] de software", r"software engineer",
        r"arquitet[oa] de (software|solucoes|sistemas)", r"front ?-?end", r"back ?-?end",
        r"full ?-?stack", r"mobile", r"android", r"\bios\b", r"flutter", r"react",
        r"angular", r"\bvue\b", r"node(\.?js)?", r"\bjava\b", r"python", r"\.net\b",
        r"\bc#", r"\bphp\b", r"golang", r"\bgo\b developer", r"kotlin", r"swift",
        r"javascript", r"typescript", r"ruby", r"delphi", r"cobol", r"\babap\b",
        r"analista de sistemas", r"analista desenvolvedor", r"low ?code",
    ]),
    ("Gestão de T.I.", [
        r"gerente de (ti|tecnologia|projetos de ti|sistemas)", r"coordenador(a)? de (ti|tecnologia|sistemas)",
        r"gestor(a)? de (ti|tecnologia)", r"\bcto\b", r"\bcio\b", r"head de (tecnologia|engenharia)",
        r"tech lead", r"lider tecnico", r"engineering manager",
    ]),
    ("Outros T.I.", [
        r"\bti\b", r"\bt\.i\.?", r"tecnologia da informacao", r"informatica",
        r"sistemas de informacao", r"\bsoftware\b", r"governanca de ti", r"\bitil\b",
    ]),
]

_CATEGORIAS_COMPILADAS = [
    (cat, [re.compile(p) for p in padroes]) for cat, padroes in CATEGORIAS_TI
]

# Termos que indicam que NÃO é T.I. mesmo contendo palavras ambíguas.
EXCLUSOES = [
    r"redes sociais", r"social media", r"tecnico de enfermagem", r"enfermeir",
    r"vendedor", r"motorista", r"atendente de loja", r"operador de caixa",
    r"designer grafico", r"design de interiores", r"engenheir[oa] civil",
    r"medic[oa]", r"fisioterapeut", r"professor(a)? de (matematica|portugues|historia)",
]
_EXCLUSOES = [re.compile(p) for p in EXCLUSOES]


def classificar_ti(titulo: str, descricao: str = "") -> str | None:
    """Retorna a categoria de T.I. da vaga ou None se não for de T.I."""
    t = sem_acento(titulo)
    if any(p.search(t) for p in _EXCLUSOES):
        return None
    for cat, padroes in _CATEGORIAS_COMPILADAS:
        if any(p.search(t) for p in padroes):
            return cat
    return None


def detectar_nivel(titulo: str) -> str:
    t = sem_acento(titulo)
    if re.search(r"estagi|estagio|trainee|aprendiz", t):
        return "Estágio/Trainee"
    if re.search(r"\bjunior\b|\bjr\.?\b|\bi\b$", t):
        return "Júnior"
    if re.search(r"\bpleno\b|\bpl\.?\b|\bii\b", t):
        return "Pleno"
    if re.search(r"\bsenior\b|\bsr\.?\b|\biii\b", t):
        return "Sênior"
    if re.search(r"especialista|staff|principal|arquitet", t):
        return "Especialista"
    if re.search(r"gerente|coordenador|gestor|head|lider|lead|diretor|manager", t):
        return "Liderança"
    return "Não informado"


def detectar_modalidade(*textos: str | None) -> str:
    t = sem_acento(" ".join(x for x in textos if x))
    if re.search(r"hibrid|hybrid", t):
        return "Híbrido"
    if re.search(r"remot|home ?office|teletrabalho|remote", t):
        return "Remoto"
    if re.search(r"presencial|on-?site", t):
        return "Presencial"
    return "Não informado"


# --------------------------------------------------------------------------------------
# Modelo de vaga
# --------------------------------------------------------------------------------------


@dataclass
class Vaga:
    titulo: str
    empresa: str
    url: str
    fonte: str
    cidade: str | None = None
    uf: str | None = None
    modalidade: str = "Não informado"
    publicada_em: str | None = None
    categoria: str | None = None
    nivel: str | None = None
    id: str = ""
    primeira_vez: str | None = None
    ultima_vez: str | None = None
    extras: dict = field(default_factory=dict)

    def finalizar(self) -> "Vaga":
        self.titulo = re.sub(r"\s+", " ", self.titulo or "").strip()
        self.empresa = re.sub(r"\s+", " ", self.empresa or "").strip() or "Não informada"
        if self.cidade:
            self.cidade = self.cidade.strip().title() if self.cidade.isupper() or self.cidade.islower() else self.cidade.strip()
        if self.categoria is None:
            self.categoria = classificar_ti(self.titulo)
        if self.nivel is None:
            self.nivel = detectar_nivel(self.titulo)
        if self.modalidade == "Não informado":
            self.modalidade = detectar_modalidade(self.titulo)
        if not self.id:
            chave = f"{sem_acento(self.titulo)}|{sem_acento(self.empresa)}|{self.uf}|{self.url}"
            self.id = hashlib.sha1(chave.encode()).hexdigest()[:16]
        return self

    def chave_dedup(self) -> str:
        """Mesma vaga publicada em portais diferentes."""
        return f"{sem_acento(self.titulo)}|{sem_acento(self.empresa)}|{sem_acento(self.cidade or '')}|{self.uf}"

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d["extras"]:
            d.pop("extras")
        return d


def agora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalizar_data(valor) -> str | None:
    """Aceita ISO, timestamp (ms ou s) ou dd/mm/aaaa e devolve ISO 8601 (data)."""
    if valor in (None, ""):
        return None
    try:
        if isinstance(valor, (int, float)):
            ts = valor / 1000 if valor > 1e11 else valor
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        s = str(valor).strip()
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        if m:
            return m.group(1)
    except (ValueError, OverflowError, OSError):
        pass
    return None


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------


class Http:
    """Sessão HTTP com retentativas, intervalo mínimo entre requisições e timeout."""

    def __init__(self, intervalo: float = 0.6, timeout: float = 25, tentativas: int = 3):
        self.sessao = requests.Session()
        self.sessao.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6",
        })
        self.intervalo = intervalo
        self.timeout = timeout
        self.tentativas = tentativas
        self._ultima = 0.0
        self.requisicoes = 0

    def get(self, url: str, **kwargs) -> requests.Response:
        erro: Exception | None = None
        for tentativa in range(self.tentativas):
            espera = self.intervalo - (time.monotonic() - self._ultima)
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()
            self.requisicoes += 1
            try:
                resp = self.sessao.get(url, timeout=self.timeout, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                erro = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status and 400 <= status < 500 and status != 429:
                    break
                time.sleep(2 ** tentativa)
        assert erro is not None
        raise erro

    def get_json(self, url: str, **kwargs):
        headers = {"Accept": "application/json", **kwargs.pop("headers", {})}
        return self.get(url, headers=headers, **kwargs).json()


def carregar_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao
