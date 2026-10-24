import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doe import Publicacao
from filters import FiltroConfig, classificar_com_motivo
from utils import extrair_titulo, limpar_html, normalizar


def publicacao(
    texto: str,
    categoria: str = (
        "Contratos, Editais e Avisos > "
        "Secretaria de Estado da Administração - SEAD"
    ),
    consulta: str = "aviso de licitação",
    resumo: str = "",
) -> Publicacao:
    return Publicacao(
        codigo=1,
        texto=texto,
        resumo=limpar_html(resumo or texto)[:300],
        categoria=categoria,
        data_publicacao=date(2026, 10, 23),
        consulta=consulta,
        titulo=extrair_titulo(texto),
    )


class TestTexto(unittest.TestCase):
    def test_normalizar_remove_acentos_e_tags(self) -> None:
        self.assertEqual(
            normalizar("<b>Licitação</b> Pública\xa0 "),
            "licitacao publica",
        )

    def test_extrair_titulo_ignora_cabecalho_do_orgao(self) -> None:
        texto = (
            "SECRETARIA DE ESTADO DA SAÚDE PÚBLICA\n"
            "HOSPITAL REGIONAL\n\n"
            "AVISO DE LICITAÇÃO PREGÃO ELETRÔNICO Nº 159/2026\n"
            "OBJETO: contratação de serviços."
        )
        self.assertIn("AVISO DE LICITAÇÃO", extrair_titulo(texto))


class TestFiltros(unittest.TestCase):
    def setUp(self) -> None:
        self.filtro = FiltroConfig(
            categorias_excluir=[
                "Prefeituras e Câmaras Municipais",
                "Publicações Particulares",
            ]
        )

    def test_aviso_de_licitacao_e_oportunidade(self) -> None:
        pub = publicacao(
            "AVISO DE LICITAÇÃO PREGÃO ELETRÔNICO Nº 159/2026 "
            "OBJETO: Contratação de empresa especializada em serviços."
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertTrue(ok, motivo)

    def test_extrato_de_adjudicacao_nao_e_oportunidade(self) -> None:
        pub = publicacao(
            "EXTRATO DO TERMO DE ADJUDICAÇÃO E HOMOLOGAÇÃO "
            "PREGÃO ELETRÔNICO N.º 206/26 - RP/SEAD."
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)

    def test_termo_de_inexigibilidade_nao_e_oportunidade(self) -> None:
        pub = publicacao(
            "TERMO DE INEXIGIBILIDADE DE LICITAÇÃO Nº 12/2026 "
            "O PROCURADOR-GERAL DO ESTADO..."
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)

    def test_aviso_de_adiamento_e_oportunidade(self) -> None:
        pub = publicacao(
            "AVISO DE ADIAMENTO DE LICITAÇÃO - PREGÃO ELETRÔNICO Nº 442/2026 "
            "OBJETO: aquisição de equipamentos."
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertTrue(ok, motivo)

    def test_termo_aditivo_no_resumo_com_texto_em_tabela(self) -> None:
        # Caso real da DPE/RN: o texto começa com a tabela do item, e o sinal
        # "TERMO ADITIVO" só aparece no resumo.
        pub = publicacao(
            "DPE/RN, por 1 (um) ano, para eventual contratação de serviços "
            "gráficos (item 43 - Mochila). Pregão eletrônico nº 10/2025.",
            resumo=(
                "TERMO ADITIVO DE PRORROGAÇÃO À ATA DE REGISTRO DE PREÇOS "
                "Nº 37/2025 - DPE/RN. Primeiro Termo Aditivo à Ata..."
            ),
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)

    def test_resultado_provisorio_no_resumo_nao_e_oportunidade(self) -> None:
        # Caso real da SECULT: "Edital de Apoio" no texto, mas é resultado.
        pub = publicacao(
            "Bloco IV: Edital de Apoio à Mulheres na Cultura 16/2026 "
            "Agreste / Ampla concorrência.",
            resumo=(
                "Bloco IV: Edital de Apoio à Mulheres na Cultura 16/2026. "
                "Confira abaixo o Resultado Provisório da Habilitação "
                "Documental."
            ),
            consulta="concorrência",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)

    def test_concurso_publico_nao_e_oportunidade(self) -> None:
        pub = publicacao(
            "CONCURSO PÚBLICO PARA PREENCHIMENTO DE CARGOS DE PROVIMENTO "
            "EFETIVO DO IDEMA. EDITAL DE REVOGAÇÃO DE LIMINAR.",
            consulta="concorrência",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)

    def test_processo_licitatorio_e_oportunidade(self) -> None:
        # Caso real da CAERN.
        pub = publicacao(
            "COMPANHIA DE ÁGUAS E ESGOTOS DO RIO GRANDE DO NORTE - CAERN "
            "PROCESSO LICITATÓRIO N° 52/2026 – MODO DE DISPUTA ABERTO "
            "ELETRÔNICO. Objeto: Aquisição de indicadores digitais.",
            consulta="licitação",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertTrue(ok, motivo)

    def test_irp_com_ata_de_registro_no_corpo_e_oportunidade(self) -> None:
        # Caso real da SEAD: o cabeçalho é uma IRP, mas o corpo menciona
        # "ata de registro de preços" depois dos primeiros 400 caracteres.
        texto = (
            "INTENÇÃO DE REGISTRO DE PREÇOS IRP 925538 - 227/2026. "
            "A SEAD, mediante a Coordenadoria de Compras Governamentais "
            "(COMPR/SEAD), realizará processo licitatório para registro de "
            "preços. " + ("Detalhes do objeto. " * 60) +
            "O gerenciamento da respectiva ata de registro de preços ficará "
            "a cargo da SEAD."
        )
        pub = publicacao(texto, consulta="registro de preços")
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertTrue(ok, motivo)

    def test_prefeitura_excluida_por_padrao(self) -> None:
        pub = publicacao(
            "AVISO DE LICITAÇÃO PREGÃO ELETRÔNICO Nº 011/2026",
            categoria="Prefeituras e Câmaras Municipais",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)

    def test_filtro_de_orgao_sead(self) -> None:
        filtro = FiltroConfig(categorias_incluir=["SEAD"])
        texto = "AVISO DE LICITAÇÃO PREGÃO ELETRÔNICO Nº 159/2026"

        pub_sead = publicacao(texto)
        ok, motivo = classificar_com_motivo(pub_sead, filtro)
        self.assertTrue(ok, motivo)

        pub_sesap = publicacao(
            texto,
            categoria=(
                "Contratos, Editais e Avisos > "
                "Secretaria de Estado da Saúde Pública"
            ),
        )
        ok, motivo = classificar_com_motivo(pub_sesap, filtro)
        self.assertFalse(ok, motivo)

    def test_termo_obrigatorio(self) -> None:
        filtro = FiltroConfig(termos_incluir=["medicamento"])
        pub = publicacao(
            "AVISO DE LICITAÇÃO PREGÃO ELETRÔNICO Nº 159/2026 "
            "OBJETO: aquisição de medicamentos."
        )
        ok, motivo = classificar_com_motivo(pub, filtro)
        self.assertTrue(ok, motivo)

        pub_sem_termo = publicacao(
            "AVISO DE LICITAÇÃO PREGÃO ELETRÔNICO Nº 160/2026 "
            "OBJETO: aquisição de materiais de limpeza."
        )
        ok, motivo = classificar_com_motivo(pub_sem_termo, filtro)
        self.assertFalse(ok, motivo)


class TestRegras(unittest.TestCase):
    """regras_incluir: todos os grupos precisam casar (AND de ORs)."""

    def setUp(self) -> None:
        self.filtro = FiltroConfig(
            regras_incluir=[
                ["pesquisa de precos", "consulta publica", "aviso de licitação"],
                ["tecnologia da informação", "notebook", "computação em nuvem"],
            ]
        )

    def test_passa_quando_ambos_os_grupos_casam(self) -> None:
        pub = publicacao(
            "PESQUISA DE PREÇOS N.º 12/2026. Obtenção de cotações para aquisição "
            "de notebooks para atendimento aos usuários.",
            consulta="pesquisa de preços",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertTrue(ok, motivo)

    def test_rejeita_quando_falta_o_grupo_de_objeto(self) -> None:
        # Tem a fase (pesquisa de preços) mas o objeto não é de TI.
        pub = publicacao(
            "PESQUISA DE PREÇOS N.º 13/2026. Obtenção de cotações para "
            "aquisição de materiais de limpeza e copa.",
            consulta="pesquisa de preços",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)
        self.assertIn("regra", motivo)

    def test_rejeita_quando_falta_o_grupo_de_fase(self) -> None:
        # Tem objeto de TI mas nenhuma fase da contratação no texto.
        pub = publicacao(
            "SEAD. Contratação de empresa para fornecimento de servidores "
            "e switches de rede para o data center.",
            consulta="licitação",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)
        self.assertIn("regra", motivo)

    def test_regra_aceita_termo_no_resumo(self) -> None:
        # Caso prático: o snippet traz o objeto no resumo, não no texto.
        pub = publicacao(
            "SEAD, mediante a Coordenadoria de Compras Governamentais, "
            "realizará pesquisa de preços.",
            resumo=(
                "Pesquisa de preços para contratação de serviço de computação "
                "em nuvem."
            ),
            consulta="pesquisa de preços",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertTrue(ok, motivo)

    def test_negativos_de_cabecalho_vale_mais_que_a_regra(self) -> None:
        # Um extrato de TI continua sendo descartado, mesmo casando as regras.
        pub = publicacao(
            "EXTRATO DE HOMOLOGAÇÃO. Pesquisa de preços de notebooks. "
            "Homologação do resultado.",
            consulta="pesquisa de preços",
        )
        ok, motivo = classificar_com_motivo(pub, self.filtro)
        self.assertFalse(ok, motivo)


class TestConsultasDeFasePrevia(unittest.TestCase):
    """Gatilhos de planejamento/cotação aceitos mesmo sem positivo no cabeçalho."""

    def test_pesquisa_de_precos_e_consulta_publica_sao_especificas(self) -> None:
        for consulta, texto in (
            (
                "pesquisa de preços",
                "SEAD - PESQUISA DE PREÇOS N.º 44/2026. Cotações para "
                "fornecimento de servidores.",
            ),
            (
                "consulta pública",
                "SEAD - CONSULTA PÚBLICA Nº 9/2026. Trata-se de sessão para "
                "discussão de minuta de edital de TI.",
            ),
            (
                "estudo técnico preliminar",
                "SEAD - ESTUDO TÉCNICO PRELIMINAR. Demanda por serviço de "
                "sustentação de sistemas.",
            ),
        ):
            pub = publicacao(texto, consulta=consulta)
            ok, motivo = classificar_com_motivo(pub, FiltroConfig())
            self.assertTrue(ok, f"{consulta}: {motivo}")


if __name__ == "__main__":
    unittest.main()
