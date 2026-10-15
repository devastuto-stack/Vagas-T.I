"""Testes offline do coletor (usam fixtures; não acessam a internet).

Executar: python -m unittest discover -s tests -v"""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from scraper import __main__ as principal
from scraper.comum import Vaga, classificar_ti, detectar_nivel, extrair_local, uf_de
from scraper.fontes import gupy, institucional, solides, vagas_com

FIX = Path(__file__).parent / "fixtures"


class HttpFalso:
    """Devolve a fixture conforme a URL pedida."""

    def __init__(self, rotas: dict[str, str]):
        self.rotas = rotas
        self.requisicoes = 0
        self.urls = []

    def _achar(self, url):
        self.requisicoes += 1
        self.urls.append(url)
        for trecho, arquivo in self.rotas.items():
            if trecho in url:
                return (FIX / arquivo).read_text(encoding="utf-8")
        raise RuntimeError(f"sem rota para {url}")

    def get(self, url, **_):
        return mock.Mock(text=self._achar(url))

    def get_json(self, url, **_):
        return json.loads(self._achar(url))


class TestClassificacao(unittest.TestCase):
    def test_vagas_de_ti(self):
        casos = {
            "Desenvolvedor Back-end Java Pleno": "Desenvolvimento",
            "Analista de Dados Sênior": "Dados & IA",
            "Estágio em Suporte Técnico de TI": "Suporte & Service Desk",
            "Analista de Segurança da Informação": "Segurança da Informação",
            "Engenheiro DevOps": "Infraestrutura & Cloud",
            "Analista de QA": "QA & Testes",
            "Product Owner": "Produto & Agilidade",
            "Consultor SAP FI": "ERP & Sistemas Corporativos",
            "Analista de T.I.": "Outros T.I.",
        }
        for titulo, categoria in casos.items():
            with self.subTest(titulo=titulo):
                self.assertEqual(classificar_ti(titulo), categoria)

    def test_vagas_fora_de_ti(self):
        for titulo in ["Técnico de Enfermagem", "Analista de Redes Sociais", "Vendedor Externo",
                       "Engenheiro Civil", "Auxiliar Administrativo", "Operador de Plataforma"]:
            with self.subTest(titulo=titulo):
                self.assertIsNone(classificar_ti(titulo))

    def test_nivel(self):
        self.assertEqual(detectar_nivel("Desenvolvedor Pleno"), "Pleno")
        self.assertEqual(detectar_nivel("Estágio em TI"), "Estágio/Trainee")
        self.assertEqual(detectar_nivel("Dev Sr. Python"), "Sênior")


class TestLocalizacao(unittest.TestCase):
    def test_extrair_local(self):
        self.assertEqual(extrair_local("Fortaleza / CE"), ("Fortaleza", "CE"))
        self.assertEqual(extrair_local("Recife - Pernambuco"), ("Recife", "PE"))
        self.assertEqual(extrair_local("Teresina"), ("Teresina", "PI"))
        self.assertEqual(extrair_local("Campinas / SP")[1], None)
        self.assertEqual(extrair_local(None), (None, None))

    def test_uf(self):
        self.assertEqual(uf_de("Ceará"), "CE")
        self.assertEqual(uf_de("ceara"), "CE")
        self.assertEqual(uf_de("RN"), "RN")
        self.assertIsNone(uf_de("São Paulo"))


class TestFontes(unittest.TestCase):
    def test_gupy(self):
        http = HttpFalso({"gupy": "gupy.json"})
        vagas = gupy.coletar(http, estados={"CE": "Ceará"}, termos=["desenvolvedor"])
        por_titulo = {v.titulo: v for v in vagas}
        # Vaga de São Paulo é descartada; enfermagem fica (filtro de T.I. é no orquestrador)
        self.assertNotIn("Analista de Dados Sênior", por_titulo)
        dev = por_titulo["Desenvolvedor Back-end Java Pleno"]
        self.assertEqual((dev.uf, dev.cidade, dev.modalidade, dev.nivel), ("CE", "Fortaleza", "Híbrido", "Pleno"))
        self.assertEqual(dev.publicada_em, "2026-10-14")
        self.assertIsNone(por_titulo["Técnico de Enfermagem"].categoria)
        self.assertEqual(por_titulo["Estágio em Suporte Técnico de TI"].uf, "PE")

    def test_vagas_com(self):
        html = (FIX / "vagas_com.html").read_text(encoding="utf-8")
        vagas = vagas_com.parse(html, hoje=date(2026, 10, 15))
        self.assertEqual(len(vagas), 3)
        a = vagas[0]
        self.assertEqual((a.titulo, a.empresa, a.cidade, a.uf), ("Analista de Sistemas Júnior", "Empresa Ômega", "Fortaleza", "CE"))
        self.assertEqual(a.url, "https://www.vagas.com.br/vagas/v2600001/analista-de-sistemas-junior")
        self.assertEqual(a.publicada_em, "2026-10-15")
        self.assertEqual(vagas[1].publicada_em, "2026-10-12")

    def test_vagas_com_nao_atribui_estado_a_vaga_de_outra_regiao(self):
        http = HttpFalso({"vagas.com.br": "vagas_com.html"})
        vagas = vagas_com.coletar(http, estados={"CE": "Ceará"}, termos=["ti"])
        zeta = next(v for v in vagas if v.empresa == "Empresa Zeta")
        self.assertIsNone(zeta.uf)
        self.assertIn("vagas-de-ti-em-ceara", http.urls[0])

    def test_solides(self):
        http = HttpFalso({"apigw.solides": "solides.json"})
        vagas = solides.coletar(http, estados={"CE": "Ceará"}, termos=["programador"])
        por_titulo = {v.titulo: v for v in vagas}
        delphi = por_titulo["Programador Delphi"]
        self.assertEqual((delphi.cidade, delphi.uf, delphi.empresa), ("Juazeiro do Norte", "CE", "Software Kappa"))
        self.assertEqual(delphi.publicada_em, "2026-10-11")
        self.assertEqual(por_titulo["Analista de Infraestrutura de TI"].uf, "RN")
        self.assertEqual(por_titulo["Analista de Infraestrutura de TI"].modalidade, "Remoto")

    def test_solides_cai_para_html_se_api_falhar(self):
        http = HttpFalso({"vagas.solides.com.br": "pagina_carreiras.html"})
        vagas = solides.coletar(http, estados={"BA": "Bahia"}, termos=["dev"])
        self.assertEqual({v.uf for v in vagas}, {"BA", "AL"})

    def test_portal_institucional_pagina(self):
        http = HttpFalso({"exemplo": "pagina_carreiras.html"})
        portal = {"empresa": "Exemplo", "tipo": "pagina", "url": "https://carreiras.exemplo/", "uf": "CE"}
        vagas, status = institucional.coletar(http, [portal])
        por_titulo = {v.titulo: v for v in vagas}
        self.assertEqual(por_titulo["Engenheiro de Software"].uf, "BA")
        self.assertEqual(por_titulo["Analista de Segurança da Informação"].url, "https://carreiras.exemplo/jobs/77")
        self.assertNotIn("Desenvolvedor Python", por_titulo)  # Curitiba
        self.assertTrue(status[0]["ok"])

    def test_portal_com_erro_nao_derruba_os_demais(self):
        http = HttpFalso({"exemplo": "pagina_carreiras.html"})
        portais = [{"empresa": "Fora do ar", "tipo": "pagina", "url": "https://quebrado.invalido/"},
                   {"empresa": "Exemplo", "tipo": "pagina", "url": "https://carreiras.exemplo/"}]
        vagas, status = institucional.coletar(http, portais)
        self.assertFalse(status[0]["ok"])
        self.assertTrue(status[1]["ok"])
        self.assertTrue(vagas)

    def test_config_institucional_valida(self):
        for p in institucional.carregar_portais():
            self.assertIn(p["tipo"], institucional.TIPOS)
            self.assertTrue(p.get("url") or p.get("token"))


class TestOrquestrador(unittest.TestCase):
    def _vaga(self, titulo, fonte, uf="CE", empresa="ACME", cidade="Fortaleza"):
        return Vaga(titulo=titulo, empresa=empresa, url=f"https://x/{fonte}/{titulo}", fonte=fonte,
                    cidade=cidade, uf=uf).finalizar()

    def test_deduplica_entre_portais(self):
        vagas = [self._vaga("Desenvolvedor PHP", "Gupy"), self._vaga("Desenvolvedor PHP", "Vagas.com")]
        unicas = principal.deduplicar(vagas)
        self.assertEqual(len(unicas), 1)
        self.assertEqual(unicas[0].extras["tambem_em"][0]["fonte"], "Vagas.com")

    def test_execucao_completa(self):
        def fonte_ok(_http):
            return [self._vaga("Desenvolvedor Java", "Gupy"), self._vaga("Vendedor", "Gupy"),
                    self._vaga("Analista de Dados", "Gupy", uf=None, cidade="Campinas")]

        def fonte_quebrada(_http):
            raise RuntimeError("fora do ar")

        fontes = {"ok": ("Gupy", fonte_ok), "ruim": ("Sólides", fonte_quebrada)}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(principal.FONTES, fontes, clear=True):
            dados = principal.executar(["ok", "ruim"], Path(tmp))
            self.assertEqual([v["titulo"] for v in dados["vagas"]], ["Desenvolvedor Java"])
            self.assertEqual([s["ok"] for s in dados["fontes"]], [True, False])
            primeira = dados["vagas"][0]["primeira_vez"]

            # Segunda coleta: preserva a data de primeira aparição
            dados2 = principal.executar(["ok"], Path(tmp))
            self.assertEqual(dados2["vagas"][0]["primeira_vez"], primeira)
            hist = json.loads((Path(tmp) / "historico.json").read_text())
            self.assertEqual(hist[-1]["por_uf"], {"CE": 1})


if __name__ == "__main__":
    unittest.main()
