"""Sólides Vagas (vagas.solides.com.br).

O portal é uma aplicação Next.js alimentada por uma API JSON. Tentamos primeiro a API
(`API_VAGAS`) e, se ela falhar ou mudar, caímos para a página de busca, lendo o
__NEXT_DATA__ e o JSON-LD. O extrator genérico localiza os objetos-vaga em qualquer
nível do JSON, o que deixa a coleta resistente a mudanças de formato."""

from __future__ import annotations

from ..comum import ESTADOS_NE, Http, Vaga, extrair_local, normalizar_data, uf_de
from ..extrator import campos_basicos, iterar_vagas_json, json_ld_vagas, next_data

API_VAGAS = "https://apigw.solides.com.br/jobs/v3/home/vacancy"
PAGINA_BUSCA = "https://vagas.solides.com.br/vagas/todos"
TERMOS = ["desenvolvedor", "programador", "tecnologia da informação", "analista de sistemas",
          "suporte técnico", "dados", "infraestrutura", "TI"]
POR_PAGINA = 50
MAX_PAGINAS = 3


def converter(bruto: dict) -> Vaga | None:
    c = campos_basicos(bruto)
    if not c["titulo"]:
        return None
    uf = uf_de(c["estado"])
    cidade = c["cidade"]
    if not uf:
        cidade, uf = extrair_local(" / ".join(x for x in (c["cidade"], c["estado"]) if x))
    if not uf:
        return None
    url = c["url"]
    if not url and bruto.get("slug"):
        url = f"https://vagas.solides.com.br/vaga/{bruto['slug']}"
    if not url and c["id"]:
        url = f"https://vagas.solides.com.br/vaga/{c['id']}"
    modalidade = c["modalidade"] or "Não informado"
    return Vaga(
        titulo=c["titulo"],
        empresa=c["empresa"] or "",
        url=url or "https://vagas.solides.com.br/",
        fonte="Sólides",
        cidade=cidade,
        uf=uf,
        modalidade={"remoto": "Remoto", "remote": "Remoto", "hibrido": "Híbrido", "hybrid": "Híbrido",
                    "presencial": "Presencial"}.get(modalidade.lower(), "Não informado"),
        publicada_em=normalizar_data(c["data"]),
        id=f"solides-{c['id']}" if c["id"] else "",
    )


def _da_api(http: Http, termo: str, local: str) -> list[dict]:
    brutos: list[dict] = []
    for pagina in range(1, MAX_PAGINAS + 1):
        dados = http.get_json(API_VAGAS, params={
            "title": termo, "locations": local, "page": pagina, "take": POR_PAGINA,
        })
        lote = list(iterar_vagas_json(dados))
        brutos.extend(lote)
        if len(lote) < POR_PAGINA:
            break
    return brutos


def _da_pagina(http: Http, termo: str, local: str) -> list[dict]:
    html = http.get(PAGINA_BUSCA, params={"title": termo, "locations": local}).text
    return list(iterar_vagas_json(next_data(html))) + json_ld_vagas(html)


def coletar(http: Http, estados: dict[str, str] = ESTADOS_NE, termos: list[str] = TERMOS) -> list[Vaga]:
    vagas: dict[str, Vaga] = {}
    erros: list[str] = []
    sucessos = 0
    usar_api = True
    for uf, nome in estados.items():
        for termo in termos:
            brutos: list[dict] = []
            try:
                if usar_api:
                    try:
                        brutos = _da_api(http, termo, nome)
                    except Exception as e:  # noqa: BLE001 — cai para o HTML
                        erros.append(f"API {uf}/{termo}: {e}")
                        usar_api = False
                if not usar_api:
                    brutos = _da_pagina(http, termo, nome)
            except Exception as e:  # noqa: BLE001
                erros.append(f"{uf}/{termo}: {e}")
                if not sucessos and len(erros) >= 5:
                    raise RuntimeError(erros[-1]) from e
                continue
            sucessos += 1
            for bruto in brutos:
                vaga = converter(bruto)
                if vaga:
                    vaga.finalizar()
                    vagas.setdefault(vaga.id, vaga)
    if not sucessos and erros:
        raise RuntimeError(erros[-1])
    return list(vagas.values())
