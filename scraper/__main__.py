"""Coletor de vagas de T.I. no Nordeste.

Uso:
    python -m scraper                 # executa uma coleta
    python -m scraper --loop          # coleta a cada 1h (para rodar em servidor próprio)
    python -m scraper --fontes gupy,solides
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .comum import ESTADOS_NE, Http, Vaga, agora_iso, carregar_json
from .fontes import gupy, institucional, solides, vagas_com

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "docs" / "data"
DIAS_RETENCAO = 7  # vaga some do painel se não for vista por este período
DIAS_HISTORICO = 90

FONTES = {
    "gupy": ("Gupy", gupy.coletar),
    "vagas_com": ("Vagas.com", vagas_com.coletar),
    "solides": ("Sólides", solides.coletar),
    "institucional": ("Portais institucionais", institucional.coletar),
}

log = logging.getLogger("vagas")


def coletar_fontes(nomes: list[str], http: Http) -> tuple[list[Vaga], list[dict]]:
    todas: list[Vaga] = []
    status = []
    for chave in nomes:
        rotulo, funcao = FONTES[chave]
        inicio = time.monotonic()
        try:
            resultado = funcao(http)
            detalhes = None
            if isinstance(resultado, tuple):
                resultado, detalhes = resultado
            ti = [v for v in resultado if v.categoria and v.uf in ESTADOS_NE]
            todas.extend(ti)
            item = {"fonte": rotulo, "ok": True, "coletadas": len(resultado), "ti_nordeste": len(ti)}
            if detalhes is not None:
                item["portais"] = detalhes
            log.info("%s: %d vagas (%d de T.I. no NE)", rotulo, len(resultado), len(ti))
        except Exception as e:  # noqa: BLE001 — uma fonte fora do ar não interrompe as demais
            item = {"fonte": rotulo, "ok": False, "erro": str(e)[:300]}
            log.warning("%s falhou: %s", rotulo, e)
        item["segundos"] = round(time.monotonic() - inicio, 1)
        status.append(item)
    return todas, status


def deduplicar(vagas: list[Vaga]) -> list[Vaga]:
    """Une a mesma vaga publicada em mais de um portal (mantém a 1ª e registra as demais)."""
    por_chave: dict[str, Vaga] = {}
    for v in vagas:
        existente = por_chave.get(v.chave_dedup())
        if existente is None:
            por_chave[v.chave_dedup()] = v
        elif v.fonte != existente.fonte:
            outras = existente.extras.setdefault("tambem_em", [])
            if not any(o["fonte"] == v.fonte for o in outras):
                outras.append({"fonte": v.fonte, "url": v.url})
    return list(por_chave.values())


def mesclar_com_anteriores(novas: list[Vaga], anteriores: list[dict], agora: str,
                           fontes_com_erro: set[str]) -> list[dict]:
    """Mantém a data da primeira aparição e preserva por alguns dias as vagas que não
    vieram nesta coleta (inclusive as de fontes que falharam agora)."""
    antigas = {v["id"]: v for v in anteriores}
    resultado: dict[str, dict] = {}
    for v in novas:
        d = v.to_dict()
        anterior = antigas.get(v.id)
        d["primeira_vez"] = (anterior or {}).get("primeira_vez") or agora
        d["ultima_vez"] = agora
        resultado[v.id] = d
    limite = datetime.fromisoformat(agora) - timedelta(days=DIAS_RETENCAO)
    for id_, d in antigas.items():
        if id_ in resultado:
            continue
        visto = datetime.fromisoformat(d.get("ultima_vez") or agora)
        if visto >= limite:
            resultado[id_] = d
    for d in resultado.values():
        d["ativa"] = d["ultima_vez"] == agora or d["fonte"] in fontes_com_erro
    return sorted(resultado.values(),
                  key=lambda d: (d.get("publicada_em") or d["primeira_vez"][:10], d["primeira_vez"]),
                  reverse=True)


def atualizar_historico(historico: list[dict], vagas: list[dict], agora: str) -> list[dict]:
    """Uma entrada por dia com o total de vagas ativas por estado (última coleta do dia)."""
    dia = agora[:10]
    ativas = [v for v in vagas if v.get("ativa")]
    entrada = {
        "dia": dia,
        "total": len(ativas),
        "por_uf": dict(Counter(v["uf"] for v in ativas)),
        "novas": sum(1 for v in vagas if v["primeira_vez"][:10] == dia),
    }
    historico = [h for h in historico if h["dia"] != dia] + [entrada]
    corte = (datetime.fromisoformat(agora) - timedelta(days=DIAS_HISTORICO)).date().isoformat()
    return [h for h in historico if h["dia"] >= corte]


def executar(nomes: list[str], saida: Path = SAIDA) -> dict:
    saida.mkdir(parents=True, exist_ok=True)
    arq_vagas, arq_hist = saida / "vagas.json", saida / "historico.json"
    anterior = carregar_json(arq_vagas, {"vagas": []})
    historico = carregar_json(arq_hist, [])

    http = Http()
    inicio = time.monotonic()
    agora = agora_iso()
    coletadas, status = coletar_fontes(nomes, http)
    novas = deduplicar(coletadas)
    fontes_com_erro = {s["fonte"] for s in status if not s["ok"]}
    vagas = mesclar_com_anteriores(novas, anterior.get("vagas", []), agora, fontes_com_erro)

    dados = {
        "atualizado_em": agora,
        "proxima_coleta": (datetime.fromisoformat(agora) + timedelta(hours=1)).isoformat(),
        "duracao_segundos": round(time.monotonic() - inicio, 1),
        "requisicoes": http.requisicoes,
        "fontes": status,
        "total": len(vagas),
        "vagas": vagas,
    }
    arq_vagas.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    arq_hist.write_text(json.dumps(atualizar_historico(historico, vagas, agora),
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Total: %d vagas de T.I. no Nordeste (%d do Ceará)", len(vagas),
             sum(1 for v in vagas if v["uf"] == "CE"))
    return dados


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fontes", default=",".join(FONTES), help="lista separada por vírgula: " + ",".join(FONTES))
    p.add_argument("--loop", action="store_true", help="repete a coleta a cada --intervalo minutos")
    p.add_argument("--intervalo", type=int, default=60, help="minutos entre coletas no modo --loop")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    nomes = [n.strip() for n in args.fontes.split(",") if n.strip()]
    invalidas = [n for n in nomes if n not in FONTES]
    if invalidas:
        p.error(f"fontes desconhecidas: {', '.join(invalidas)}")

    while True:
        dados = executar(nomes)
        if not args.loop:
            # Falha apenas se TODAS as fontes falharem (sinaliza problema no Actions).
            return 0 if any(s["ok"] for s in dados["fontes"]) else 1
        log.info("Próxima coleta em %d minutos", args.intervalo)
        time.sleep(args.intervalo * 60)


if __name__ == "__main__":
    sys.exit(main())
