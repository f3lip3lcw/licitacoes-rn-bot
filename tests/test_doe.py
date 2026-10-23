import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doe import DOEAPI, DOEAPIError


class RespostaFalsa:
    def __init__(self, status=200, dados=None, headers=None, texto=""):
        self.status_code = status
        self._dados = dados
        self.headers = headers or {}
        self.text = texto

    def json(self):
        if isinstance(self._dados, Exception):
            raise self._dados
        if self._dados is None:
            raise ValueError("sem JSON")
        return self._dados


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0
        self.headers = {}

    def request(self, *args, **kwargs):
        self.chamadas += 1
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class TestRateLimit(unittest.TestCase):
    def test_429_com_espera_curta_aguarda_e_tenta_de_novo(self):
        sessao = SessaoFalsa(
            [
                RespostaFalsa(429, {"retry_after_sec": 3}),
                RespostaFalsa(200, {"ok": True}),
            ]
        )
        api = DOEAPI(session=sessao, pausa=0)

        with patch("doe.time.sleep") as dormir:
            resultado = api._request("GET", "/teste")

        self.assertEqual(resultado, {"ok": True})
        self.assertEqual(sessao.chamadas, 2)
        dormir.assert_called_once_with(4)

    def test_429_com_espera_longa_aborta_sem_dormir(self):
        sessao = SessaoFalsa(
            [
                RespostaFalsa(
                    429,
                    {
                        "error": "rate_limit_exceeded",
                        "limit": 100,
                        "window_sec": 3600,
                        "retry_after_sec": 2765,
                    },
                )
            ]
        )
        api = DOEAPI(session=sessao, pausa=0)

        with patch("doe.time.sleep") as dormir:
            with self.assertRaises(DOEAPIError) as contexto:
                api._request("POST", "/public/search", json={})

        erro = contexto.exception
        self.assertTrue(erro.permanente)
        self.assertEqual(erro.retry_after, 2765)
        self.assertEqual(sessao.chamadas, 1)
        dormir.assert_not_called()

    def test_429_usa_header_retry_after_quando_nao_ha_json(self):
        resposta = RespostaFalsa(
            429, ValueError("sem json"), headers={"Retry-After": "7"}
        )
        self.assertEqual(DOEAPI._retry_after(resposta), 7)

    def test_400_nao_repete_e_e_permanente(self):
        sessao = SessaoFalsa(
            [RespostaFalsa(400, {"erro": "parametro invalido"}, texto="bad request")]
        )
        api = DOEAPI(session=sessao, pausa=0)

        with patch("doe.time.sleep") as dormir:
            with self.assertRaises(DOEAPIError) as contexto:
                api._request("POST", "/public/search", json={})

        self.assertTrue(contexto.exception.permanente)
        self.assertEqual(sessao.chamadas, 1)
        dormir.assert_not_called()


class TestBusca(unittest.TestCase):
    def test_payload_usa_intervalo_ano_e_mapeia_campos(self):
        class APIEspia(DOEAPI):
            def __init__(self):
                super().__init__(session=SessaoFalsa([]), pausa=0)
                self.chamadas = []

            def _request(self, metodo, caminho, **kwargs):
                self.chamadas.append((metodo, caminho, kwargs))
                return {
                    "rowCount": 1,
                    "list": [
                        {
                            "codigo": 123,
                            "texto": "<p>AVISO DE LICITAÇÃO PREGÃO 1/2026</p>",
                            "resumo": "Aviso de licitação",
                            "nomeCategoria": (
                                "Contratos, Editais e Avisos > "
                                "Secretaria de Estado da Administração - SEAD"
                            ),
                            "dataPublicacao": "2026-10-23",
                        }
                    ],
                }

        api = APIEspia()
        resultado = api.buscar(
            "licitação", date(2026, 10, 1), date(2026, 10, 23), max_paginas=1
        )

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].codigo, 123)
        self.assertEqual(resultado[0].orgao, "Secretaria de Estado da Administração - SEAD")
        self.assertEqual(resultado[0].data_publicacao, date(2026, 10, 23))

        metodo, caminho, kwargs = api.chamadas[0]
        self.assertEqual(metodo, "POST")
        self.assertEqual(caminho, "/public/search")
        self.assertEqual(kwargs["json"]["intervaloAno"], "01/10/2026-23/10/2026")
        self.assertEqual(kwargs["json"]["codigoDiario"], 121)
        self.assertEqual(kwargs["json"]["palavras"], "licitação")

    def test_busca_vazia_nao_chama_api(self):
        class APIEspia(DOEAPI):
            def __init__(self):
                super().__init__(session=SessaoFalsa([]), pausa=0)
                self.chamou = False

            def _request(self, *args, **kwargs):
                self.chamou = True
                return {}

        api = APIEspia()
        self.assertEqual(api.buscar("  ", date(2026, 10, 1), date(2026, 10, 2)), [])
        self.assertFalse(api.chamou)


if __name__ == "__main__":
    unittest.main()
