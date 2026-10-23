"""Filtros de relevância para separar oportunidades de licitação de ruído."""
from __future__ import annotations

from dataclasses import dataclass, field

from doe import Publicacao
from utils import normalizar

# Termos negativos observados no início das publicações. A ideia é olhar só o
# começo do texto (cabeçalho), porque o objeto da licitação pode conter palavras
# como "contratação" sem que a publicação seja um contrato.
NEGATIVOS_CABECALHO = (
    "extrato",
    "termo aditivo",
    "termo de aditivo",
    "termo de prorrogacao",
    "apostilamento",
    "termo de apostilamento",
    "termo de contrato",
    "extrato de contrato",
    "termo de inexigibilidade",
    "termo de dispensa",
    "termo de adjudicacao",
    "termo de homologacao",
    "termo de ratificacao",
    "resultado",
    "homologacao",
    "adjudicacao",
    "julgamento",
    "ata de registro",
    "portaria",
    "resolucao",
    "instrucao normativa",
    "sancao administrativa",
    "penalidade",
    "impedimento de licitar",
    "impugnacao",
    "recurso administrativo",
    "revogacao",
    "suspensao",
    "cancelamento",
    "errata",
    "retificacao",
    "designacao",
    "nomeacao",
    "exoneracao",
    # Concursos e seleções de pessoal que às vezes aparecem fora da categoria
    # "Concurso e Processo Seletivos".
    "concurso publico",
    "processo seletivo",
    "selecao de pessoal",
    "vagas reservadas",
    "cargos de provimento",
    "tutela provisoria",
    "revogacao de liminar",
)

POSITIVOS_CABECALHO = (
    "aviso de licitacao",
    "aviso de abertura",
    "aviso aos licitantes",
    "aviso licitacao",
    "aviso de adiamento",
    "aviso de reabertura",
    "aviso de contratacao direta",
    "aviso de pregao",
    "edital",
    "pregao eletronico",
    "pregao presencial",
    "processo licitatorio",
    "procedimento licitatorio",
    "dispensa eletronica",
    "dispensa de licitacao",
    "chamamento publico",
    "credenciamento",
    "selecao publica",
    "manifestacao de interesse",
    "intencao de registro de precos",
    "registro de precos",
    "concorrencia",
    "tomada de precos",
    "convite",
    "leilao",
    "dialogo competitivo",
    "procedimento de manifestacao",
    "comunica a abertura",
    "torna publico",
    "convoca",
)

# Consultas que já são específicas o suficiente. Se o cabeçalho não tiver nem
# termo positivo nem negativo, aceitamos o resultado dessas buscas.
CONSULTAS_ESPECIFICAS = {
    "aviso de licitacao",
    "aviso de abertura",
    "edital de licitacao",
    "chamamento publico",
    "credenciamento",
    "dispensa eletronica",
    "selecao publica",
    "manifestacao de interesse",
    "intencao de registro de precos",
    "concorrencia eletronica",
    "tomada de precos",
    "leilao",
}


@dataclass
class FiltroConfig:
    categorias_incluir: list[str] = field(default_factory=list)
    categorias_excluir: list[str] = field(default_factory=list)
    termos_incluir: list[str] = field(default_factory=list)
    termos_excluir: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._cat_inc = [normalizar(x) for x in self.categorias_incluir if x]
        self._cat_exc = [normalizar(x) for x in self.categorias_excluir if x]
        self._term_inc = [normalizar(x) for x in self.termos_incluir if x]
        self._term_exc = [normalizar(x) for x in self.termos_excluir if x]


def classificar_com_motivo(
    pub: Publicacao, filtro: FiltroConfig
) -> tuple[bool, str]:
    """Devolve (relevante, motivo) para facilitar o modo --debug."""
    categoria = normalizar(pub.categoria)

    if filtro._cat_inc and not any(t in categoria for t in filtro._cat_inc):
        return False, "categoria fora dos filtros de inclusão"

    for termo in filtro._cat_exc:
        if termo and termo in categoria:
            return False, f"categoria excluída: {termo}"

    texto = normalizar(pub.texto_limpo)

    if filtro._term_inc and not any(t in texto for t in filtro._term_inc):
        return False, "não contém nenhum termo obrigatório"

    for termo in filtro._term_exc:
        if termo and termo in texto:
            return False, f"contém termo excluído: {termo}"

    bases = [texto, normalizar(pub.resumo)]

    # Negativos: só o começo (cabeçalho). Isso evita rejeitar uma IRP porque o
    # corpo menciona "ata de registro de preços" mais adiante.
    cabecalhos_negativos = [base[:400] for base in bases if base]
    for termo in NEGATIVOS_CABECALHO:
        if any(termo in cabecalho for cabecalho in cabecalhos_negativos):
            return False, f"cabeçalho negativo: {termo}"

    # Positivos: uma janela um pouco maior, para pegar títulos depois do nome
    # do órgão.
    cabecalhos_positivos = [base[:800] for base in bases if base]
    for termo in POSITIVOS_CABECALHO:
        if any(termo in cabecalho for cabecalho in cabecalhos_positivos):
            return True, f"cabeçalho positivo: {termo}"

    if normalizar(pub.consulta) in CONSULTAS_ESPECIFICAS:
        return True, "consulta específica"

    return False, "sem sinal positivo no cabeçalho"


def classificar(pub: Publicacao, filtro: FiltroConfig) -> bool:
    ok, _ = classificar_com_motivo(pub, filtro)
    return ok
