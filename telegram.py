"""Notificação via Telegram."""
from __future__ import annotations

import html
import logging
import time
from typing import Optional

import requests

LOGGER = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    """Erro ao falar com a API do Telegram."""


def esc(texto: str) -> str:
    """Escapa texto para o parse_mode HTML do Telegram."""
    return html.escape(texto or "", quote=False)


def esc_url(url: str) -> str:
    """Escapa URL para uso dentro de href."""
    return html.escape(url or "", quote=True)


class Telegram:
    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.thread_id = (thread_id or "").strip() or None
        self.timeout = timeout

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.chat_id)

    def _post(self, metodo: str, **kwargs) -> dict:
        if not self.configurado:
            raise TelegramError(
                "TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID não configurados"
            )

        url = f"https://api.telegram.org/bot{self.token}/{metodo}"
        ultimo_erro: Optional[BaseException] = None

        for tentativa in range(1, 4):
            try:
                resposta = requests.post(url, timeout=self.timeout, **kwargs)

                if resposta.status_code == 429:
                    espera = int(resposta.headers.get("Retry-After", "5"))
                    LOGGER.warning("Telegram pediu para aguardar %ss", espera)
                    time.sleep(espera)
                    continue

                if resposta.status_code >= 400:
                    raise TelegramError(
                        f"HTTP {resposta.status_code}: {resposta.text[:500]}"
                    )

                dados = resposta.json()
                if not dados.get("ok"):
                    raise TelegramError(str(dados)[:500])
                return dados

            except (requests.RequestException, ValueError, TelegramError) as exc:
                ultimo_erro = exc
                if tentativa < 3:
                    espera = 2 ** tentativa
                    LOGGER.warning(
                        "Falha no Telegram (%s). Tentativa %s/3; aguardando %ss",
                        exc,
                        tentativa,
                        espera,
                    )
                    time.sleep(espera)

        raise TelegramError(f"Falha ao enviar mensagem: {ultimo_erro}") from ultimo_erro

    def enviar_texto(self, texto: str, silencioso: bool = False) -> dict:
        payload = {
            "chat_id": self.chat_id,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": bool(silencioso),
        }
        if self.thread_id:
            payload["message_thread_id"] = int(self.thread_id)
        return self._post("sendMessage", json=payload)

    def enviar_documento(
        self,
        conteudo: bytes,
        nome: str,
        mimetype: str,
        legenda: str,
        silencioso: bool = False,
    ) -> dict:
        dados = {
            "chat_id": self.chat_id,
            "caption": (legenda or "")[:1024],
            "parse_mode": "HTML",
            "disable_notification": bool(silencioso),
        }
        if self.thread_id:
            dados["message_thread_id"] = int(self.thread_id)

        arquivos = {
            "document": (nome, conteudo, mimetype or "application/pdf")
        }
        return self._post("sendDocument", data=dados, files=arquivos)

    def testar(self) -> dict:
        return self.enviar_texto(
            "✅ <b>Bot DOE-RN configurado com sucesso.</b>\n"
            "A partir de agora você receberá as licitações encontradas."
        )
