"""Funções de texto compartilhadas pelo bot."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_TAG_RE = re.compile(r"<[^>]+>")
_ESPACO_RE = re.compile(r"\s+")
_LINHA_RE = re.compile(r"[\r\n]+")

# Usado para escolher uma linha que pareça ser o título da publicação.
_POSITIVOS_TITULO = (
    "aviso",
    "edital",
    "pregao",
    "concorrencia",
    "dispensa",
    "credenciamento",
    "chamamento",
    "selecao",
    "manifestacao",
    "registro de precos",
    "leilao",
    "dialogo competitivo",
    "convoca",
    "contratacao direta",
)


def limpar_html(texto: str) -> str:
    """Remove tags HTML, entidades e espaços repetidos."""
    if not texto:
        return ""
    texto = _TAG_RE.sub(" ", str(texto))
    texto = html.unescape(texto)
    texto = texto.replace("\xa0", " ")
    return _ESPACO_RE.sub(" ", texto).strip()


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços normalizados (para comparação)."""
    texto = limpar_html(texto).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return _ESPACO_RE.sub(" ", texto).strip()


def truncar(texto: str, limite: int, sufixo: str = "...") -> str:
    """Trunca sem cortar no meio de uma palavra quando possível."""
    texto = (texto or "").strip()
    if len(texto) <= limite:
        return texto
    corte = texto[: max(0, limite - len(sufixo))].rstrip()
    return corte + sufixo


def hash_conteudo(texto: str) -> str:
    """Hash estável do começo do texto, para deduplicar publicações repetidas."""
    base = normalizar(texto)[:4000]
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def extrair_titulo(texto: str, resumo: str = "") -> str:
    """Tenta extrair um título curto do texto da publicação."""
    base = limpar_html(texto or resumo)
    if not base:
        return ""

    linhas = [
        linha.strip(" -–—:;")
        for linha in _LINHA_RE.split(base)
        if linha.strip()
    ]
    for linha in linhas:
        if any(p in normalizar(linha) for p in _POSITIVOS_TITULO):
            return truncar(linha, 180)

    return truncar(linhas[0] if linhas else base, 180)
