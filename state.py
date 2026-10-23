"""Estado persistente: o que já foi notificado, para não repetir alerta."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class Estado:
    def __init__(self, caminho: str, retencao_dias: int = 60) -> None:
        self.caminho = Path(caminho)
        self.retencao_dias = max(1, int(retencao_dias))
        self.dados: dict = {"version": 1, "seen": {}}
        self.carregar()

    def carregar(self) -> None:
        if not self.caminho.exists():
            return

        try:
            with self.caminho.open("r", encoding="utf-8") as fh:
                dados = json.load(fh)
            if not isinstance(dados, dict) or not isinstance(dados.get("seen"), dict):
                raise ValueError("formato inválido")
            self.dados = dados
        except (ValueError, OSError) as exc:
            # Estado corrompido não derruba o bot: recomeça do zero, guardando
            # o arquivo ruim para investigar depois.
            backup = self.caminho.with_suffix(self.caminho.suffix + ".bak")
            try:
                self.caminho.replace(backup)
            except OSError:
                pass
            LOGGER.warning(
                "Estado inválido (%s). Recomeçando; backup em %s", exc, backup
            )
            self.dados = {"version": 1, "seen": {}}

        self._podar()

    def _podar(self) -> None:
        """Descarta chaves mais velhas que a retenção, para o arquivo não crescer."""
        limite = datetime.now(timezone.utc) - timedelta(days=self.retencao_dias)
        vistos: dict[str, str] = {}

        for chave, valor in self.dados.get("seen", {}).items():
            try:
                quando = datetime.fromisoformat(str(valor))
            except (TypeError, ValueError):
                continue
            if quando.tzinfo is None:
                quando = quando.replace(tzinfo=timezone.utc)
            if quando >= limite:
                vistos[chave] = valor

        self.dados["seen"] = vistos

    def visto(self, chaves: list[str]) -> bool:
        return any(chave in self.dados["seen"] for chave in chaves)

    def marcar(self, chaves: list[str]) -> None:
        agora = datetime.now(timezone.utc).isoformat()
        for chave in chaves:
            self.dados["seen"][chave] = agora

    def salvar(self) -> None:
        """Escreve de forma atômica (arquivo temporário + rename)."""
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        fd, temporario = tempfile.mkstemp(
            prefix=".seen-", suffix=".json", dir=str(self.caminho.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.dados, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(temporario, self.caminho)
        finally:
            if os.path.exists(temporario):
                os.unlink(temporario)
