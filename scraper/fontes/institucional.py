"""Portais de carreira institucionais de empresas do Nordeste.

A lista fica em config/portais_institucionais.json. Tipos suportados:
  - "greenhouse": {"token": "<board>"}   -> boards-api.greenhouse.io (API pública)
  - "lever":      {"token": "<empresa>"} -> api.lever.co (API pública)
  - "pagina":     {"url": "https://..."} -> qualquer página de carreiras; lê dados
                   estruturados schema.org/JobPosting (JSON-LD) e __NEXT_DATA__
                   (funciona com páginas de carreira Gupy, Sólides, Inhire etc.)

Campos opcionais:
  "uf": estado-sede da empresa;
  "assumir_uf": true para atribuir "uf" às vagas sem local informado (use só para
                empresas que contratam apenas naquele estado)."""

from __future__ import annotations

import json
from pathlib import Path

from ..comum import Http, Vaga, extrair_local, normalizar_data, uf_de
from ..extrator import campos_basicos, iterar_vagas_json, json_ld_vagas, next_data

CONFIG = Path(__file__).resolve().parents[2] / "config" / "portais_institucionais.json"


def _vaga(portal: dict, titulo, url, local_texto, data, id_vaga, modalidade=None, estado=None) -> Vaga | None:
    cidade, uf = extrair_local(local_texto)
    uf = uf_de(estado) or uf
    if not uf:
        # Local fora do Nordeste ou desconhecido: descarta, exceto quando o portal é de
        # empresa que só contrata no próprio estado (assumir_uf) e a vaga não diz o local
        # ou é remota.
        remota = "remot" in (local_texto or "").lower()
        if not portal.get("assumir_uf") or (local_texto and not remota):
            return None
        uf = portal.get("uf")
    if not uf or not titulo:
        return None
    return Vaga(
        titulo=titulo,
        empresa=portal["empresa"],
        url=url or portal.get("url") or "",
        fonte="Portal institucional",
        cidade=cidade,
        uf=uf,
        modalidade=modalidade or "Não informado",
        publicada_em=normalizar_data(data),
        id=f"inst-{portal['empresa']}-{id_vaga}" if id_vaga else "",
    )


def _greenhouse(http: Http, portal: dict) -> list[Vaga]:
    dados = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{portal['token']}/jobs")
    return [v for j in dados.get("jobs", []) if (v := _vaga(
        portal, j.get("title"), j.get("absolute_url"), (j.get("location") or {}).get("name"),
        j.get("updated_at"), j.get("id")))]


def _lever(http: Http, portal: dict) -> list[Vaga]:
    dados = http.get_json(f"https://api.lever.co/v0/postings/{portal['token']}", params={"mode": "json"})
    vagas = []
    for j in dados if isinstance(dados, list) else []:
        cat = j.get("categories") or {}
        modalidade = {"remote": "Remoto", "hybrid": "Híbrido", "on-site": "Presencial"}.get(
            str(j.get("workplaceType") or "").lower())
        v = _vaga(portal, j.get("text"), j.get("hostedUrl"), cat.get("location"),
                  j.get("createdAt"), j.get("id"), modalidade)
        if v:
            vagas.append(v)
    return vagas


def _pagina(http: Http, portal: dict) -> list[Vaga]:
    html = http.get(portal["url"]).text
    brutos = json_ld_vagas(html) + list(iterar_vagas_json(next_data(html)))
    vagas = []
    for b in brutos:
        c = campos_basicos(b)
        url = c["url"]
        if url and url.startswith("/"):
            url = portal["url"].rstrip("/") + url
        v = _vaga(portal, c["titulo"], url, c["cidade"], c["data"], c["id"],
                  estado=c["estado"])
        if v:
            vagas.append(v)
    return vagas


TIPOS = {"greenhouse": _greenhouse, "lever": _lever, "pagina": _pagina}


def carregar_portais(caminho: Path = CONFIG) -> list[dict]:
    with open(caminho, encoding="utf-8") as f:
        return [p for p in json.load(f)["portais"] if p.get("ativo", True)]


def coletar(http: Http, portais: list[dict] | None = None) -> tuple[list[Vaga], list[dict]]:
    """Retorna (vagas, status por portal)."""
    portais = carregar_portais() if portais is None else portais
    vagas: dict[str, Vaga] = {}
    status = []
    for portal in portais:
        try:
            encontradas = TIPOS[portal["tipo"]](http, portal)
            for v in encontradas:
                v.finalizar()
                vagas.setdefault(v.id, v)
            status.append({"empresa": portal["empresa"], "ok": True, "total": len(encontradas)})
        except Exception as e:  # noqa: BLE001 — um portal fora do ar não derruba os demais
            status.append({"empresa": portal["empresa"], "ok": False, "erro": str(e)[:200]})
    return list(vagas.values()), status
