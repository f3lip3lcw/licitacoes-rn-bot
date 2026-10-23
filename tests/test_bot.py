import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import deduplicar_por_codigo
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


if __name__ == "__main__":
    unittest.main()
