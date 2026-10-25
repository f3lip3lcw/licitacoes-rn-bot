import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import deduplicar_por_codigo, montar_relatorio, registrar_resumo
from doe import Publicacao


def publicacao(codigo: int, texto: str) -> Publicacao:
    return Publicacao(
        codigo=codigo,
        texto=texto,
        resumo=texto[:300],
        categoria="Secretaria de Estado da Administração - SEAD",
        data_publicacao=date(2026, 10, 23),
        consulta="licitação",
    )


class TestDeduplicacao(unittest.TestCase):
    def test_mantem_o_texto_mais_completo_para_o_mesmo_codigo(self) -> None:
        curto = publicacao(385140, "REGISTRO DE PREÇOS IRP 925538 - 227/2026")
        completo = publicacao(
            385140,
            "INTENÇÃO DE REGISTRO DE PREÇOS. IRP 925538 - 227/2026. "
            "A SEAD realizará processo licitatório para registro de preços.",
        )

        resultado = deduplicar_por_codigo([curto, completo, curto])

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].texto, completo.texto)

    def test_ignora_codigo_vazio(self) -> None:
        resultado = deduplicar_por_codigo([publicacao(0, "sem código")])
        self.assertEqual(resultado, [])


class TestRelatorio(unittest.TestCase):
    AGORA = datetime(2026, 10, 26, 8, 7)

    def test_sem_novidades_avisa_que_o_servico_rodou(self) -> None:
        msg = montar_relatorio(
            {
                "SEAD geral": {
                    "encontradas": 8,
                    "apos_filtro": 2,
                    "enviadas": 0,
                    "falhas": 0,
                    "erros": 0,
                }
            },
            self.AGORA,
        )

        self.assertIn("Relatório DOE-RN", msg)
        self.assertIn("26/10/2026 às 08:07", msg)
        self.assertIn("8 encontrada(s)", msg)
        self.assertIn("Nenhuma oportunidade nova", msg)

    def test_com_envios_diz_que_esta_acima(self) -> None:
        msg = montar_relatorio(
            {"TI": {"encontradas": 9, "apos_filtro": 3, "enviadas": 3}},
            self.AGORA,
        )

        self.assertIn("3 enviada(s)", msg)
        self.assertIn("As publicações desta janela estão acima", msg)
        self.assertNotIn("Nenhuma oportunidade", msg)

    def test_lista_os_dois_perfis_e_destaca_falha(self) -> None:
        msg = montar_relatorio(
            {
                "SEAD geral": {"encontradas": 4, "apos_filtro": 1, "enviadas": 1},
                "TI": {"encontradas": 4, "apos_filtro": 0, "enviadas": 0, "falhas": 2},
            },
            self.AGORA,
        )

        self.assertIn("<b>SEAD geral:</b>", msg)
        self.assertIn("<b>TI:</b>", msg)
        self.assertIn("2 falha(s)", msg)


class TestRegistroDeResumo(unittest.TestCase):
    def test_conserva_os_perfis_no_mesmo_arquivo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            estado = str(Path(tmp) / "seen.json")

            registrar_resumo(
                estado,
                "SEAD geral",
                {"janela": "23/10 a 24/10", "encontradas": 8, "enviadas": 0},
            )
            registrar_resumo(
                estado,
                "TI",
                {"janela": "23/10 a 24/10", "encontradas": 9, "enviadas": 0},
            )

            dados = json.loads(
                (Path(tmp) / "resumo.json").read_text(encoding="utf-8")
            )

        self.assertEqual(set(dados["perfis"]), {"SEAD geral", "TI"})
        self.assertEqual(dados["perfis"]["SEAD geral"]["encontradas"], 8)
        self.assertTrue(dados["perfis"]["TI"]["quando"])

    def test_resumo_corrompido_nao_derruba(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "resumo.json"
            caminho.write_text("{{{isso nao e json", encoding="utf-8")

            registrar_resumo(str(Path(tmp) / "seen.json"), "TI", {"enviadas": 1})
            dados = json.loads(caminho.read_text(encoding="utf-8"))

        self.assertEqual(list(dados["perfis"]), ["TI"])


if __name__ == "__main__":
    unittest.main()
