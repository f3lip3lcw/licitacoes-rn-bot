"""Cliente da API pública do Diário Oficial do RN (SDOE).

O portal antigo (diariooficial.rn.gov.br) é ASP.NET WebForms e só tem busca
até 17/11/2022. A busca atual fica no SDOE:

    https://deirn.sdoe.com.br/diariooficialweb/#/busca-avancada?diario=MTIx

O SPA usa a API pública abaixo, que devolve JSON e não exige login:

    POST /diariooficial/public/search

Este módulo encapsula essa API, com retry, paginação e tratamento de erros.
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests

from utils import extrair_titulo, limpar_html

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://deirn.sdoe.com.br/diariooficial"
WEB_URL = "https://deirn.sdoe.com.br/diariooficialweb"
CODIGO_DIARIO = 121  # Departamento Estadual de Imprensa do RN - DEI/RN
DIARIO_B64 = base64.b64encode(str(CODIGO_DIARIO).encode()).decode()


class DOEAPIError(RuntimeError):
    """Erro de comunicação ou de contrato com a API do DOE-RN."""

    def __init__(
        self,
        mensagem: str,
        retry_after: Optional[int] = None,
        permanente: bool = False,
    ) -> None:
        super().__init__(mensagem)
        self.retry_after = retry_after
        self.permanente = permanente


@dataclass
class Publicacao:
    codigo: int
    texto: str
    resumo: str
    categoria: str
    data_publicacao: date
    consulta: str
    titulo: str = ""
    link: str = ""
    link_busca: str = ""
    metadados: dict[str, Any] = field(default_factory=dict)

    @property
    def orgao(self) -> str:
        """Último nível da categoria, que normalmente é o órgão."""
        partes = [p.strip() for p in (self.categoria or "").split(">") if p.strip()]
        return partes[-1] if partes else (self.categoria or "Órgão não informado")

    @property
    def texto_limpo(self) -> str:
        return limpar_html(self.texto or self.resumo)


class DOEAPI:
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = 45,
        pausa: float = 1.0,
        max_espera: int = 120,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pausa = max(0.0, float(pausa))
        # Se a API pedir para esperar mais que isso, é melhor abortar a
        # execução do que ficar dormindo por quase uma hora.
        self.max_espera = max(1, int(max_espera))
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36 LicitacoesRNBot/1.0"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "pt-BR,pt;q=0.9",
                "Origin": "https://deirn.sdoe.com.br",
                "Referer": f"{WEB_URL}/",
            }
        )
        self._ultima_requisicao = 0.0

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        """Mantém um intervalo mínimo entre chamadas à API."""
        if self.pausa <= 0:
            return
        decorrido = time.monotonic() - self._ultima_requisicao
        if decorrido < self.pausa:
            time.sleep(self.pausa - decorrido)
        self._ultima_requisicao = time.monotonic()

    @staticmethod
    def _retry_after(resposta: requests.Response) -> int:
        """Lê o tempo de espera do JSON de erro (ou do header Retry-After)."""
        valor: Any = None
        try:
            dados = resposta.json()
            if isinstance(dados, dict):
                valor = dados.get("retry_after_sec") or dados.get("retry_after")
        except ValueError:
            pass
        if valor is None:
            valor = resposta.headers.get("Retry-After", "10")
        try:
            return max(1, int(float(valor)))
        except (TypeError, ValueError):
            return 10

    def _request(self, metodo: str, caminho: str, **kwargs: Any) -> Any:
        """Executa uma chamada HTTP com throttle, retry e tratamento de 429.

        A API pública limita a 100 requisições por hora. Quando o limite é
        atingido, ela devolve HTTP 429 com ``retry_after_sec``. Se a espera for
        curta, o bot aguarda e tenta de novo; se for longa, levanta
        ``DOEAPIError`` com ``permanente=True`` para a execução parar sem
        ficar travada por dezenas de minutos.
        """
        url = f"{self.base_url}{caminho}"
        max_tentativas = 4

        for tentativa in range(1, max_tentativas + 1):
            self._throttle()

            try:
                resposta = self.session.request(
                    metodo, url, timeout=self.timeout, **kwargs
                )
            except requests.RequestException as exc:
                if tentativa >= max_tentativas:
                    raise DOEAPIError(
                        f"Falha de rede ao acessar {url}: {exc}"
                    ) from exc
                espera = 2 ** tentativa
                LOGGER.warning(
                    "Falha de rede (%s). Tentativa %s/%s; aguardando %ss",
                    exc,
                    tentativa,
                    max_tentativas,
                    espera,
                )
                time.sleep(espera)
                continue

            if resposta.status_code == 429:
                espera = self._retry_after(resposta)
                if espera > self.max_espera:
                    raise DOEAPIError(
                        (
                            f"Limite de requisições da API do DOE-RN atingido. "
                            f"Tente novamente em {espera // 60} min "
                            f"({espera}s). A API permite 100 requisições por hora."
                        ),
                        retry_after=espera,
                        permanente=True,
                    )
                if tentativa >= max_tentativas:
                    raise DOEAPIError(
                        f"Rate limit persistente em {url} (espera {espera}s).",
                        retry_after=espera,
                    )
                LOGGER.warning(
                    "Rate limit da API; aguardando %ss (tentativa %s/%s)",
                    espera,
                    tentativa,
                    max_tentativas,
                )
                time.sleep(espera + 1)
                continue

            if resposta.status_code >= 500:
                if tentativa >= max_tentativas:
                    raise DOEAPIError(
                        f"HTTP {resposta.status_code} em {url}: "
                        f"{resposta.text[:300]}"
                    )
                espera = 2 ** tentativa
                LOGGER.warning(
                    "Erro %s na API; tentativa %s/%s em %ss",
                    resposta.status_code,
                    tentativa,
                    max_tentativas,
                    espera,
                )
                time.sleep(espera)
                continue

            if resposta.status_code >= 400:
                # 4xx (salvo 429) é erro de contrato/parâmetro: não adianta
                # repetir e cada tentativa só gasta o limite da API.
                raise DOEAPIError(
                    f"HTTP {resposta.status_code} em {url}: "
                    f"{resposta.text[:300]}",
                    permanente=True,
                )

            try:
                return resposta.json()
            except ValueError as exc:
                raise DOEAPIError(
                    f"Resposta não-JSON em {url}: {resposta.text[:200]}",
                    permanente=True,
                ) from exc

        raise DOEAPIError(f"Falha ao acessar {url} após {max_tentativas} tentativas")

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------
    def buscar(
        self,
        palavras: str,
        inicio: date,
        fim: date,
        max_results: int = 100,
        max_paginas: int = 5,
        categoria_id: Optional[int] = None,
    ) -> list[Publicacao]:
        """Executa a busca avançada e devolve as publicações encontradas.

        O campo ``intervaloAno`` é o que a própria interface envia. Apesar do
        nome, ele recebe o intervalo de datas no formato DD/MM/AAAA-DD/MM/AAAA.
        """
        if inicio > fim:
            raise ValueError("Data inicial maior que a data final")
        if not palavras.strip():
            return []

        resultados: list[Publicacao] = []
        first = 0

        for pagina in range(max(1, max_paginas)):
            payload: dict[str, Any] = {
                "palavras": palavras,
                "codigoDiario": CODIGO_DIARIO,
                "intervaloAno": (
                    f"{inicio.strftime('%d/%m/%Y')}-"
                    f"{fim.strftime('%d/%m/%Y')}"
                ),
                "first": first,
                "maxResults": max_results,
            }
            if categoria_id is not None:
                payload["codigoCategoria"] = categoria_id

            dados = self._request("POST", "/public/search", json=payload)
            lista = dados.get("list") or []
            total = int(dados.get("rowCount") or 0)

            for item in lista:
                publicacao = self._item_para_publicacao(item, palavras)
                if publicacao is not None:
                    resultados.append(publicacao)

            first += len(lista)
            LOGGER.debug(
                "Busca %r página %s: %s itens (total %s)",
                palavras,
                pagina + 1,
                len(lista),
                total,
            )

            if not lista or first >= total or len(lista) < max_results:
                break

        return resultados

    def _item_para_publicacao(
        self, item: dict[str, Any], consulta: str
    ) -> Optional[Publicacao]:
        try:
            codigo = int(item.get("codigo") or 0)
        except (TypeError, ValueError):
            codigo = 0
        if not codigo:
            return None

        texto = item.get("texto") or ""
        resumo = item.get("resumo") or limpar_html(texto)[:300]
        categoria = item.get("nomeCategoria") or ""

        data_txt = str(item.get("dataPublicacao") or "")[:10]
        try:
            data_publicacao = date.fromisoformat(data_txt)
        except ValueError:
            LOGGER.warning("Data inválida na publicação %s: %r", codigo, data_txt)
            data_publicacao = date.today()

        titulo = item.get("titulo") or extrair_titulo(texto, resumo)

        return Publicacao(
            codigo=codigo,
            texto=texto,
            resumo=limpar_html(resumo),
            categoria=categoria,
            data_publicacao=data_publicacao,
            consulta=consulta,
            titulo=limpar_html(titulo),
        )

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------
    @staticmethod
    def link_busca(palavras: str, inicio: date, fim: date) -> str:
        """Link para a busca avançada já preenchida no portal."""
        params = {
            "diario": DIARIO_B64,
            "inicio": inicio.strftime("%d/%m/%Y"),
            "fim": fim.strftime("%d/%m/%Y"),
            "palavra": palavras,
            "consultar": "true",
        }
        return f"{WEB_URL}/#/busca-avancada?{urlencode(params)}"

    def detalhes(self, codigo: int) -> dict[str, Any]:
        """Busca os metadados e o arquivo (quando houver) de uma publicação.

        A rota /visualizar-publicacao do SPA não recebe o código que aparece na
        busca; ela recebe o ``idMateriaArquivo``. Por isso são necessárias duas
        chamadas: uma para descobrir ``codigoPublicacao`` e ``codigoCliente`` e
        outra para obter ``idMateriaArquivo``.
        """
        materia = self._request(
            "GET",
            "/public/busca-avancada/consultarMateriaBuscaAvancada",
            params={"codigoMateria": codigo},
        )

        codigo_publicacao = materia.get("codigoPublicacao")
        codigo_cliente = materia.get("codigoCliente")
        if not codigo_publicacao or not codigo_cliente:
            raise DOEAPIError(
                f"Metadados insuficientes para a publicação {codigo}"
            )

        publicacao = self._request(
            "GET",
            "/public/busca-avancada/consultarPublicacao",
            params={
                "codigoCliente": codigo_cliente,
                "codigoPublicacao": codigo_publicacao,
                "codigoMateriaPublicacao": codigo,
                "codigoDiario": CODIGO_DIARIO,
            },
        )

        publicacao["_codigoMateria"] = codigo
        publicacao["_codigoPublicacao"] = codigo_publicacao
        publicacao["_codigoCliente"] = codigo_cliente
        return publicacao

    @staticmethod
    def link_direto_de_detalhes(detalhes: dict[str, Any]) -> str:
        id_arquivo = detalhes.get("idMateriaArquivo")
        if not id_arquivo:
            raise DOEAPIError("Publicação sem idMateriaArquivo")

        codigo_b64 = base64.b64encode(str(id_arquivo).encode()).decode()
        return (
            f"{WEB_URL}/#/visualizar-publicacao"
            f"?diario={DIARIO_B64}&publicacao={quote(codigo_b64, safe='')}"
        )

    def link_direto(self, codigo: int) -> str:
        return self.link_direto_de_detalhes(self.detalhes(codigo))

    @staticmethod
    def arquivo_de_detalhes(
        detalhes: dict[str, Any],
    ) -> Optional[tuple[bytes, str, str]]:
        """Devolve (conteúdo, nome, mimetype) do PDF, se a publicação tiver arquivo."""
        arquivo = detalhes.get("arquivo")
        if not arquivo:
            return None
        try:
            conteudo = base64.b64decode(arquivo)
        except Exception as exc:  # noqa: BLE001 - base64 inválido vem da API
            raise DOEAPIError("Arquivo da publicação inválido") from exc

        nome = detalhes.get("nomeArquivo") or "publicacao.pdf"
        mimetype = detalhes.get("tipoArquivo") or "application/pdf"
        return conteudo, nome, mimetype
