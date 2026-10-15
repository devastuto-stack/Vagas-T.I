"""Extração genérica de vagas a partir de JSON arbitrário (APIs e __NEXT_DATA__)
e de páginas HTML com dados estruturados schema.org/JobPosting (JSON-LD).

É usada pelas fontes cujo formato pode mudar sem aviso (Sólides, portais
institucionais), tornando o coletor tolerante a pequenas alterações de layout."""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from bs4 import BeautifulSoup

CAMPOS_TITULO = ("title", "name", "jobName", "titulo", "cargo", "position", "text")
CAMPOS_EMPRESA = ("companyName", "company", "careerPageName", "empresa", "hiringOrganization",
                  "organization", "employer")
CAMPOS_CIDADE = ("city", "cidade", "jobCity", "addressLocality", "location", "local", "workplace")
CAMPOS_ESTADO = ("state", "uf", "estado", "jobState", "addressRegion", "region")
CAMPOS_URL = ("url", "jobUrl", "link", "applyUrl", "absolute_url", "hostedUrl", "redirectLink",
              "jobLink")
CAMPOS_DATA = ("publishedDate", "publishedAt", "createdAt", "datePosted", "publicationDate",
               "created_at", "updated_at", "dataPublicacao", "startDate")
CAMPOS_REMOTO = ("isRemoteWork", "homeOffice", "remote", "isRemote", "workplaceType",
                 "jobLocationType", "workModel", "modality")


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor.strip() or None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, dict):
        for k in ("name", "nome", "title", "label", "code", "sigla", "value"):
            if k in valor:
                return _texto(valor[k])
    if isinstance(valor, list) and valor:
        return _texto(valor[0])
    return None


def _primeiro(d: dict, campos: tuple[str, ...]) -> Any:
    for c in campos:
        if c in d and d[c] not in (None, "", [], {}):
            return d[c]
    return None


def parece_vaga(d: dict) -> bool:
    """Heurística: objeto com título e pelo menos um indício de vaga."""
    if not isinstance(d, dict):
        return False
    titulo = _primeiro(d, CAMPOS_TITULO)
    if not isinstance(titulo, str) or len(titulo) < 3:
        return False
    indicios = sum(1 for grupo in (CAMPOS_EMPRESA, CAMPOS_CIDADE, CAMPOS_ESTADO, CAMPOS_URL,
                                   CAMPOS_DATA, CAMPOS_REMOTO)
                   if _primeiro(d, grupo) is not None)
    return indicios >= 2 or d.get("@type") == "JobPosting"


def iterar_vagas_json(dado: Any, _prof: int = 0) -> Iterator[dict]:
    """Percorre recursivamente o JSON e devolve objetos que parecem vagas."""
    if _prof > 12:
        return
    if isinstance(dado, dict):
        if parece_vaga(dado):
            yield dado
            return
        for v in dado.values():
            yield from iterar_vagas_json(v, _prof + 1)
    elif isinstance(dado, list):
        for item in dado:
            yield from iterar_vagas_json(item, _prof + 1)


def campos_basicos(d: dict) -> dict:
    """Normaliza um objeto-vaga de formato desconhecido em campos padronizados."""
    local = d.get("jobLocation") or d.get("address") or {}
    if isinstance(local, list):
        local = local[0] if local else {}
    endereco = local.get("address", local) if isinstance(local, dict) else {}
    if not isinstance(endereco, dict):
        endereco = {}

    cidade = _texto(_primeiro(d, CAMPOS_CIDADE)) or _texto(_primeiro(endereco, CAMPOS_CIDADE))
    estado = _texto(_primeiro(d, CAMPOS_ESTADO)) or _texto(_primeiro(endereco, CAMPOS_ESTADO))

    remoto_bruto = _primeiro(d, CAMPOS_REMOTO)
    if isinstance(remoto_bruto, bool):
        modalidade = "Remoto" if remoto_bruto else None
    else:
        modalidade = _texto(remoto_bruto)

    return {
        "titulo": _texto(_primeiro(d, CAMPOS_TITULO)),
        "empresa": _texto(_primeiro(d, CAMPOS_EMPRESA)),
        "cidade": cidade,
        "estado": estado,
        "url": _texto(_primeiro(d, CAMPOS_URL)),
        "data": _primeiro(d, CAMPOS_DATA),
        "modalidade": modalidade,
        "id": _texto(d.get("id") or d.get("_id") or d.get("identifier")),
    }


def json_ld_vagas(html: str) -> list[dict]:
    """Extrai objetos JobPosting de <script type="application/ld+json">."""
    soup = BeautifulSoup(html, "lxml")
    vagas = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            dado = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        pilha = [dado]
        while pilha:
            item = pilha.pop()
            if isinstance(item, list):
                pilha.extend(item)
            elif isinstance(item, dict):
                tipo = item.get("@type")
                if tipo == "JobPosting" or (isinstance(tipo, list) and "JobPosting" in tipo):
                    vagas.append(item)
                if "@graph" in item:
                    pilha.append(item["@graph"])
                if "itemListElement" in item:
                    pilha.append(item["itemListElement"])
                if "item" in item and isinstance(item["item"], (dict, list)):
                    pilha.append(item["item"])
    return vagas


def next_data(html: str) -> Any:
    """Retorna o JSON de __NEXT_DATA__ (sites Next.js) ou None."""
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
