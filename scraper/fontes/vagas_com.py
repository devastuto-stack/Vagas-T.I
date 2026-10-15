"""vagas.com.br — páginas de busca por termo e localidade.

URLs no formato https://www.vagas.com.br/vagas-de-<termo>-em-<local>?pagina=<n>
Cada vaga é um <li class="vaga ..."> contendo:
    h2.cargo > a.link-detalhes-vaga (título + href /vagas/v<ID>/...)
    span.emprVaga                    (empresa)
    span.vaga-local                  (ex.: "Fortaleza / CE")
    span.data-publicacao             (ex.: "Hoje", "15/10/2026")
O parser tem alternativas para pequenas variações do HTML."""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..comum import ESTADOS_NE, Http, Vaga, extrair_local, normalizar_data, sem_acento

BASE = "https://www.vagas.com.br"
TERMOS = ["ti", "tecnologia", "desenvolvedor", "programador", "analista-de-sistemas",
          "suporte-tecnico", "dados", "infraestrutura", "seguranca-da-informacao"]
MAX_PAGINAS = 3


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sem_acento(texto)).strip("-")


def _data_relativa(texto: str | None, hoje: date | None = None) -> str | None:
    if not texto:
        return None
    hoje = hoje or date.today()
    t = sem_acento(texto)
    if "hoje" in t:
        return hoje.isoformat()
    if "ontem" in t:
        return (hoje - timedelta(days=1)).isoformat()
    m = re.search(r"ha (\d+) dias?", t)
    if m:
        return (hoje - timedelta(days=int(m.group(1)))).isoformat()
    return normalizar_data(texto)


def _texto(el) -> str | None:
    return el.get_text(" ", strip=True) if el else None


def parse(html: str, hoje: date | None = None) -> list[Vaga]:
    soup = BeautifulSoup(html, "lxml")
    itens = soup.select("li.vaga") or soup.select("[class*=vaga] .link-detalhes-vaga")
    vagas = []
    for li in itens:
        if li.name == "a":
            li = li.find_parent("li") or li.parent
        link = li.select_one("a.link-detalhes-vaga") or li.select_one("h2 a") or li.find("a", href=re.compile(r"/vagas/v\d+"))
        if not link:
            continue
        titulo = link.get("title") or _texto(link)
        href = urljoin(BASE, link.get("href", ""))
        empresa = _texto(li.select_one(".emprVaga")) or _texto(li.select_one("[class*=empr]"))
        local = _texto(li.select_one(".vaga-local")) or _texto(li.select_one("[class*=local]"))
        data = _texto(li.select_one(".data-publicacao")) or _texto(li.select_one("[class*=data]"))
        cidade, uf = extrair_local(local)
        id_vaga = link.get("data-id-vaga") or (re.search(r"/v(\d+)", href) or [None, None])[1]
        vagas.append(Vaga(
            titulo=titulo or "",
            empresa=empresa or "",
            url=href,
            fonte="Vagas.com",
            cidade=cidade,
            uf=uf,
            publicada_em=_data_relativa(data, hoje),
            id=f"vagascom-{id_vaga}" if id_vaga else "",
            extras={"local": local} if local else {},
        ))
    return vagas


def coletar(http: Http, estados: dict[str, str] = ESTADOS_NE, termos: list[str] = TERMOS) -> list[Vaga]:
    vagas: dict[str, Vaga] = {}
    erros: list[str] = []
    sucessos = 0
    for uf, nome in estados.items():
        for termo in termos:
            for pagina in range(1, MAX_PAGINAS + 1):
                url = f"{BASE}/vagas-de-{_slug(termo)}-em-{_slug(nome)}"
                try:
                    html = http.get(url, params={"pagina": pagina} if pagina > 1 else None).text
                except Exception as e:  # noqa: BLE001
                    erros.append(f"{url}: {e}")
                    if not sucessos and len(erros) >= 5:
                        raise RuntimeError(erros[0]) from e
                    break
                sucessos += 1
                encontradas = parse(html)
                for v in encontradas:
                    local = v.extras.pop("local", None)
                    if v.uf is None and not local:
                        v.uf = uf  # sem local informado: a busca já é restrita ao estado
                    v.finalizar()
                    vagas.setdefault(v.id, v)
                if len(encontradas) < 20:
                    break
    if not sucessos and erros:
        raise RuntimeError(erros[0])
    return list(vagas.values())
