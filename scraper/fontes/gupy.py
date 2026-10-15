"""Gupy — portal público de vagas (portal.gupy.io).

Usa a API pública consumida pelo próprio portal:
    GET https://portal.api.gupy.io/api/v1/jobs?jobName=<termo>&state=<estado>&limit=<n>&offset=<n>
Resposta: {"data": [ {name, careerPageName, city, state, jobUrl, publishedDate,
           isRemoteWork, workplaceType, ...} ], "pagination": {total, limit, offset}}

Como a Gupy hospeda as páginas de carreira de muitas empresas do Nordeste
(ex.: <empresa>.gupy.io), esta fonte também cobre parte dos portais institucionais."""

from __future__ import annotations

from ..comum import ESTADOS_NE, Http, Vaga, detectar_modalidade, normalizar_data, uf_de

API = "https://portal.api.gupy.io/api/v1/jobs"
LIMITE = 100
MAX_PAGINAS = 3

TERMOS = [
    "desenvolvedor", "programador", "software", "dados", "analista de sistemas",
    "suporte técnico", "infraestrutura", "devops", "segurança da informação", "QA",
    "tecnologia da informação", "TI", "front-end", "back-end", "full stack",
    "cloud", "redes", "product owner", "UX", "SAP",
]

MODALIDADE_GUPY = {"remote": "Remoto", "hybrid": "Híbrido", "on-site": "Presencial"}


def converter(item: dict) -> Vaga | None:
    uf = uf_de(item.get("state"))
    if not uf:
        return None
    modalidade = MODALIDADE_GUPY.get(str(item.get("workplaceType") or "").lower())
    if not modalidade:
        modalidade = "Remoto" if item.get("isRemoteWork") else detectar_modalidade(item.get("name"))
    return Vaga(
        titulo=item.get("name") or "",
        empresa=item.get("careerPageName") or "",
        url=item.get("jobUrl") or f"https://portal.gupy.io/job/{item.get('id')}",
        fonte="Gupy",
        cidade=item.get("city"),
        uf=uf,
        modalidade=modalidade,
        publicada_em=normalizar_data(item.get("publishedDate")),
        id=f"gupy-{item['id']}" if item.get("id") else "",
    )


def coletar(http: Http, estados: dict[str, str] = ESTADOS_NE, termos: list[str] = TERMOS) -> list[Vaga]:
    vagas: dict[str, Vaga] = {}
    erros: list[str] = []
    sucessos = 0
    for uf, nome_estado in estados.items():
        for termo in termos:
            for pagina in range(MAX_PAGINAS):
                try:
                    dados = http.get_json(API, params={
                        "jobName": termo, "state": nome_estado,
                        "limit": LIMITE, "offset": pagina * LIMITE,
                    })
                except Exception as e:  # noqa: BLE001 — uma busca com erro não derruba a fonte
                    erros.append(f"{uf}/{termo}: {e}")
                    if not sucessos and len(erros) >= 5:
                        raise RuntimeError(erros[0]) from e
                    break
                sucessos += 1
                itens = dados.get("data") or []
                for item in itens:
                    vaga = converter(item)
                    if vaga:
                        vaga.finalizar()
                        vagas.setdefault(vaga.id, vaga)
                total = (dados.get("pagination") or {}).get("total") or 0
                if len(itens) < LIMITE or (pagina + 1) * LIMITE >= total:
                    break
    if not sucessos and erros:
        raise RuntimeError(erros[0])
    return list(vagas.values())
