#!/usr/bin/env python3
"""Monitor de licitações do Diário Oficial do RN (DOE-RN).

Uso:
    python bot.py --dias 2 --dry-run
    python bot.py --dias 2
    python bot.py --test-telegram
"""
from __future__ import annotations

import argparse
import copy
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from doe import DOEAPI, DOEAPIError, Publicacao
from filters import FiltroConfig, classificar_com_motivo
from state import Estado
from telegram import Telegram, TelegramError, esc, esc_url
from utils import hash_conteudo, limpar_html, normalizar, truncar

LOGGER = logging.getLogger("bot")

TZ = ZoneInfo("America/Sao_Paulo")

# 1164 = categoria "Secretaria de Estado da Administração - SEAD" no DOE-RN.
DEFAULTS: dict[str, Any] = {
    "diario": {"codigo": 121, "nome": "DOE-RN"},
    "periodo": {"dias": 2},
    "buscas": [
        {"palavras": "licitação", "codigoCategoria": 1164},
        {"palavras": "pregão eletrônico", "codigoCategoria": 1164},
        {"palavras": "registro de preços", "codigoCategoria": 1164},
        {"palavras": "dispensa", "codigoCategoria": 1164},
        {"palavras": "credenciamento", "codigoCategoria": 1164},
        {"palavras": "chamamento público", "codigoCategoria": 1164},
        {"palavras": "coordenadoria de compras", "codigoCategoria": 1164},
        {"palavras": "concorrência", "codigoCategoria": 1164},
    ],
    "filtros": {
        "categorias_incluir": ["Secretaria de Estado da Administração - SEAD"],
        "categorias_excluir": [
            "Prefeituras e Câmaras Municipais",
            "Publicações Particulares",
            "Concurso e Processo Seletivos",
            "Concursos e Seleções",
        ],
        "termos_incluir": [],
        "termos_excluir": [],
    },
    "telegram": {
        "anexar_pdf": False,
        "silencioso": False,
        "limite_notificacoes": 20,
    },
    "links": {"direto": False, "max_diretos": 5},
    "estado": {"arquivo": ".state/seen.json", "retencao_dias": 60},
}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Monitora licitações no Diário Oficial do RN usando a API pública "
            "do SDOE (a mesma da Busca Avançada)."
        )
    )
    parser.add_argument("--config", default="config.yaml", help="Arquivo YAML de configuração")
    parser.add_argument("--estado", default=None, help="Arquivo de estado (padrão: config)")
    parser.add_argument("--data", help="Data única, DD/MM/AAAA")
    parser.add_argument("--desde", help="Data inicial, DD/MM/AAAA")
    parser.add_argument("--ate", help="Data final, DD/MM/AAAA")
    parser.add_argument("--dias", type=int, help="Janela em dias terminando hoje")
    parser.add_argument("--orgao", help="Filtrar por órgão/categoria (ex.: SEAD)")
    parser.add_argument(
        "--incluir-municipios",
        action="store_true",
        help="Incluir Prefeituras e Câmaras Municipais",
    )
    parser.add_argument(
        "--incluir-publicacoes-particulares",
        action="store_true",
        help="Incluir Publicações Particulares",
    )
    parser.add_argument("--limite", type=int, help="Máximo de notificações nesta execução")
    parser.add_argument(
        "--no-link-direto",
        action="store_true",
        help="Não resolver o link direto da publicação",
    )
    parser.add_argument(
        "--anexar-pdf",
        action="store_true",
        help="Enviar o PDF da publicação como documento",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Não envia nada e não marca itens como vistos",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Envia uma mensagem de teste e sai",
    )
    parser.add_argument("--debug", action="store_true", help="Log detalhado")
    return parser.parse_args(argv)


def carregar_config(caminho: str) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(caminho)
    if not path.exists():
        raise SystemExit(f"Configuração não encontrada: {path}")

    with path.open("r", encoding="utf-8") as fh:
        dados = yaml.safe_load(fh) or {}

    if not isinstance(dados, dict):
        raise SystemExit("O config.yaml precisa conter um objeto YAML no nível raiz.")

    for secao, valores in dados.items():
        if isinstance(valores, dict) and isinstance(cfg.get(secao), dict):
            cfg[secao].update(valores)
        else:
            cfg[secao] = valores

    return cfg


def parse_data(valor: str) -> date:
    valor = (valor or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            pass
    raise SystemExit(f"Data inválida: {valor!r}. Use DD/MM/AAAA ou AAAA-MM-DD.")


def resolver_periodo(args: argparse.Namespace, cfg: dict[str, Any]) -> tuple[date, date]:
    hoje = datetime.now(TZ).date()
    dias_config = max(1, int(cfg.get("periodo", {}).get("dias", 2)))
    dias = max(1, args.dias) if args.dias else dias_config

    if args.data:
        inicio = fim = parse_data(args.data)
    elif args.desde or args.ate:
        inicio = parse_data(args.desde) if args.desde else hoje - timedelta(days=dias - 1)
        fim = parse_data(args.ate) if args.ate else hoje
    else:
        inicio = hoje - timedelta(days=dias - 1)
        fim = hoje

    if inicio > fim:
        raise SystemExit("A data inicial não pode ser maior que a data final.")

    if fim > hoje:
        LOGGER.warning("Data final %s no futuro; ajustando para hoje (%s).", fim, hoje)
        fim = hoje
        if inicio > fim:
            inicio = fim

    return inicio, fim


def aplicar_overrides(cfg: dict[str, Any], args: argparse.Namespace) -> None:
    filtros = cfg.setdefault("filtros", {})

    if args.orgao:
        filtros["categorias_incluir"] = [args.orgao]

    if args.incluir_municipios:
        filtros["categorias_excluir"] = [
            item
            for item in (filtros.get("categorias_excluir") or [])
            if "prefeitura" not in normalizar(item) and "camara" not in normalizar(item)
        ]

    if args.incluir_publicacoes_particulares:
        filtros["categorias_excluir"] = [
            item
            for item in (filtros.get("categorias_excluir") or [])
            if "publicacoes particulares" not in normalizar(item)
        ]

    if args.limite is not None:
        cfg.setdefault("telegram", {})["limite_notificacoes"] = args.limite

    if args.no_link_direto:
        cfg.setdefault("links", {})["direto"] = False

    if args.anexar_pdf:
        cfg.setdefault("telegram", {})["anexar_pdf"] = True

    if args.estado:
        cfg.setdefault("estado", {})["arquivo"] = args.estado


def montar_mensagem(
    pub: Publicacao,
    link_direto: str = "",
    link_busca: str = "",
    curta: bool = False,
) -> str:
    resumo = truncar(pub.resumo or pub.texto_limpo, 180 if curta else 320)

    linhas: list[str] = []
    if not curta:
        linhas.append("<b>DOE-RN — nova publicação</b>")

    linhas.append(f"<b>Publicado:</b> {pub.data_publicacao:%d/%m/%Y}")
    linhas.append(f"<b>Órgão:</b> {esc(pub.orgao)}")

    if not curta:
        linhas.append(f"<b>Categoria:</b> {esc(pub.categoria)}")

    linhas.append(f"<b>Título:</b> {esc(pub.titulo or 'Publicação do DOE-RN')}")

    if resumo:
        linhas.append(f"<b>Resumo:</b> {esc(resumo)}")

    links = []
    if link_direto:
        links.append(f'<a href="{esc_url(link_direto)}">Abrir publicação</a>')
    if link_busca:
        links.append(f'<a href="{esc_url(link_busca)}">Buscar no DOE</a>')
    if links:
        linhas.append(" | ".join(links))

    if not curta:
        linhas.append(f"<code>código {pub.codigo}</code>")

    return "\n".join(linhas)


def imprimir_dry_run(pub: Publicacao, mensagem: str) -> None:
    print("\n" + "=" * 78)
    print(f"DATA: {pub.data_publicacao:%d/%m/%Y} | CÓDIGO: {pub.codigo}")
    print(f"ÓRGÃO: {pub.orgao}")
    print(f"CATEGORIA: {pub.categoria}")
    print(f"TÍTULO: {pub.titulo}")
    print(f"CONSULTA: {pub.consulta}")
    print(f"RESUMO: {truncar(pub.resumo or pub.texto_limpo, 500)}")
    print(f"LINK DIRETO: {pub.link or '-'}")
    print(f"LINK BUSCA: {pub.link_busca or '-'}")
    print("-" * 78)
    print("MENSAGEM (HTML):")
    print(mensagem)


def coletar(
    api: DOEAPI, cfg: dict[str, Any], inicio: date, fim: date
) -> tuple[list[Publicacao], int, bool]:
    """Roda as buscas do config. Devolve (publicações, falhas, bloqueado).

    ``bloqueado`` = a API pediu espera longa e as buscas restantes foram
    interrompidas. O que já veio continua válido.
    """
    todas: list[Publicacao] = []
    falhas = 0
    bloqueado = False
    buscas = cfg.get("buscas") or []

    for busca in buscas:
        if isinstance(busca, str):
            palavras = busca
            max_results = 100
            max_paginas = 2
            categoria_id = None
        else:
            palavras = str(busca.get("palavras") or "").strip()
            max_results = int(busca.get("maxResults", 100))
            max_paginas = int(busca.get("maxPaginas", 2))
            categoria_id = busca.get("codigoCategoria")

        if not palavras:
            continue

        try:
            resultados = api.buscar(
                palavras,
                inicio,
                fim,
                max_results=max_results,
                max_paginas=max_paginas,
                categoria_id=categoria_id,
            )
        except DOEAPIError as exc:
            falhas += 1
            LOGGER.error("Busca %r falhou: %s", palavras, exc)
            if exc.permanente:
                bloqueado = True
                LOGGER.warning(
                    "Interrompendo as buscas restantes para não insistir "
                    "contra o limite da API."
                )
                break
            continue

        LOGGER.info("Busca %r: %d resultado(s)", palavras, len(resultados))
        todas.extend(resultados)

    return todas, falhas, bloqueado


def deduplicar_por_codigo(publicacoes: list[Publicacao]) -> list[Publicacao]:
    """Uma publicação por código, preferindo o texto mais completo.

    A mesma matéria aparece em consultas diferentes com snippets de tamanhos
    diferentes; guardar o mais longo evita perder um termo que só aparece no
    texto completo.
    """
    por_codigo: dict[int, Publicacao] = {}
    for pub in publicacoes:
        if not pub.codigo:
            continue
        atual = por_codigo.get(pub.codigo)
        if atual is None or len(pub.texto or "") > len(atual.texto or ""):
            por_codigo[pub.codigo] = pub
    return list(por_codigo.values())


def deduplicar_por_conteudo(publicacoes: list[Publicacao]) -> tuple[list[Publicacao], int]:
    vistos: set[str] = set()
    unicas: list[Publicacao] = []
    removidas = 0

    for pub in publicacoes:
        chave = hash_conteudo(pub.texto or pub.resumo)
        if chave in vistos:
            removidas += 1
            continue
        vistos.add(chave)
        unicas.append(pub)

    return unicas, removidas


def chaves_publicacao(pub: Publicacao) -> list[str]:
    return [
        f"cod:{pub.codigo}",
        f"hash:{hash_conteudo(pub.texto or pub.resumo)}",
    ]


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_dotenv()

    telegram = Telegram(
        token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        thread_id=os.getenv("TELEGRAM_THREAD_ID"),
    )

    if args.test_telegram:
        if not telegram.configurado:
            LOGGER.error(
                "Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env "
                "ou no ambiente antes de testar."
            )
            return 2
        try:
            telegram.testar()
            LOGGER.info("Mensagem de teste enviada com sucesso.")
            return 0
        except TelegramError as exc:
            LOGGER.error("Falha no teste do Telegram: %s", exc)
            return 1

    try:
        cfg = carregar_config(args.config)
    except SystemExit as exc:
        LOGGER.error("%s", exc)
        return 2

    aplicar_overrides(cfg, args)

    try:
        inicio, fim = resolver_periodo(args, cfg)
    except SystemExit as exc:
        LOGGER.error("%s", exc)
        return 2

    if not args.dry_run and not telegram.configurado:
        LOGGER.error(
            "Telegram não configurado. Defina TELEGRAM_BOT_TOKEN e "
            "TELEGRAM_CHAT_ID, ou rode com --dry-run."
        )
        return 2

    filtros_cfg = cfg.get("filtros") or {}
    filtro = FiltroConfig(
        categorias_incluir=filtros_cfg.get("categorias_incluir") or [],
        categorias_excluir=filtros_cfg.get("categorias_excluir") or [],
        termos_incluir=filtros_cfg.get("termos_incluir") or [],
        termos_excluir=filtros_cfg.get("termos_excluir") or [],
    )

    estado_cfg = cfg.get("estado") or {}
    estado = Estado(
        estado_cfg.get("arquivo", ".state/seen.json"),
        retencao_dias=int(estado_cfg.get("retencao_dias", 60)),
    )

    api = DOEAPI()
    LOGGER.info(
        "Janela de busca: %s a %s",
        inicio.strftime("%d/%m/%Y"),
        fim.strftime("%d/%m/%Y"),
    )
    if filtro.categorias_incluir:
        LOGGER.info("Filtro de órgão/categoria: %s", ", ".join(filtro.categorias_incluir))

    todas, falhas_busca, bloqueado = coletar(api, cfg, inicio, fim)
    if not todas:
        if bloqueado or (falhas_busca and falhas_busca == len(cfg.get("buscas") or [])):
            LOGGER.error("Nenhum resultado: todas as buscas falharam ou foram bloqueadas.")
            return 1
        LOGGER.info("Nenhuma publicação encontrada na janela informada.")
        return 0
    if bloqueado:
        LOGGER.warning(
            "A API bloqueou parte das buscas; processando os %d resultado(s) "
            "obtidos antes do bloqueio.",
            len(todas),
        )

    unicas = deduplicar_por_codigo(todas)
    LOGGER.info("Resultados brutos: %d | únicos por código: %d", len(todas), len(unicas))

    candidatas: list[Publicacao] = []
    for pub in unicas:
        ok, motivo = classificar_com_motivo(pub, filtro)
        if ok:
            candidatas.append(pub)
        elif args.debug:
            LOGGER.debug(
                "Ignorada %s (%s): %s | %s",
                pub.codigo,
                pub.data_publicacao,
                motivo,
                pub.titulo,
            )

    candidatas.sort(key=lambda p: (p.data_publicacao, p.codigo), reverse=True)
    candidatas, duplicadas_conteudo = deduplicar_por_conteudo(candidatas)

    LOGGER.info(
        "Após filtros: %d | duplicadas por conteúdo: %d",
        len(candidatas),
        duplicadas_conteudo,
    )

    novas: list[Publicacao] = []
    for pub in candidatas:
        chaves = chaves_publicacao(pub)
        if estado.visto(chaves):
            if args.debug:
                LOGGER.debug("Já notificada: %s", pub.codigo)
            continue
        pub.metadados["chaves"] = chaves
        novas.append(pub)

    LOGGER.info("Novas (ainda não notificadas): %d", len(novas))

    limite = max(1, int((cfg.get("telegram") or {}).get("limite_notificacoes", 20)))
    para_notificar = novas[:limite]
    restantes = novas[limite:]

    if restantes:
        LOGGER.warning(
            "%d oportunidade(s) acima do limite de %d não serão notificadas nesta execução.",
            len(restantes),
            limite,
        )

    links_cfg = cfg.get("links") or {}
    resolver_link = bool(links_cfg.get("direto", True))
    max_diretos = max(0, int(links_cfg.get("max_diretos", 30)))
    links_resolvidos = 0
    anexar_pdf = bool((cfg.get("telegram") or {}).get("anexar_pdf", False))
    silencioso = bool((cfg.get("telegram") or {}).get("silencioso", False))

    # Link direto e PDF custam chamadas extras; o limite de detalhes evita
    # estourar a cota da API quando há muitas publicações.
    for pub in para_notificar:
        pub.link_busca = api.link_busca(pub.consulta, inicio, fim)

        precisa_detalhes = anexar_pdf or (
            resolver_link and links_resolvidos < max_diretos
        )
        if not precisa_detalhes:
            continue

        try:
            detalhes = api.detalhes(pub.codigo)
            pub.metadados["detalhes"] = detalhes
            if resolver_link and links_resolvidos < max_diretos:
                pub.link = api.link_direto_de_detalhes(detalhes)
                links_resolvidos += 1
        except DOEAPIError as exc:
            LOGGER.warning(
                "Não foi possível obter detalhes/link direto de %s: %s",
                pub.codigo,
                exc,
            )

        if args.debug:
            LOGGER.debug("Link de %s: %s", pub.codigo, pub.link or pub.link_busca)

    enviados = 0
    erros = 0

    for pub in para_notificar:
        detalhes = pub.metadados.get("detalhes")
        arquivo = None

        if anexar_pdf and detalhes:
            try:
                arquivo = api.arquivo_de_detalhes(detalhes)
            except DOEAPIError as exc:
                LOGGER.warning("PDF indisponível para %s: %s", pub.codigo, exc)

        usar_documento = bool(arquivo)
        mensagem = montar_mensagem(
            pub,
            link_direto=pub.link,
            link_busca=pub.link_busca,
            curta=usar_documento,
        )

        if args.dry_run:
            imprimir_dry_run(pub, mensagem)
            continue

        try:
            if usar_documento and arquivo is not None:
                conteudo, nome, mimetype = arquivo
                telegram.enviar_documento(
                    conteudo,
                    nome,
                    mimetype,
                    mensagem,
                    silencioso=silencioso,
                )
            else:
                telegram.enviar_texto(mensagem, silencioso=silencioso)
        except TelegramError as exc:
            erros += 1
            LOGGER.error("Falha ao notificar %s: %s", pub.codigo, exc)
            continue

        estado.marcar(pub.metadados["chaves"])
        estado.salvar()
        enviados += 1
        LOGGER.info(
            "Notificada %s | %s | %s",
            pub.codigo,
            pub.data_publicacao,
            pub.titulo,
        )
        time.sleep(1.0)

    if restantes and not args.dry_run:
        try:
            telegram.enviar_texto(
                (
                    f"<b>Foram encontradas mais {len(restantes)} oportunidade(s)</b> "
                    f"além do limite de {limite} desta execução.\n"
                    "Ajuste os filtros ou consulte a Busca Avançada do DOE-RN."
                ),
                silencioso=silencioso,
            )
        except TelegramError as exc:
            LOGGER.error("Falha ao enviar o aviso de limite: %s", exc)

    if args.dry_run:
        LOGGER.info(
            "Dry-run concluído: %d candidata(s), %d nova(s), nenhuma mensagem enviada.",
            len(candidatas),
            len(novas),
        )
        return 0

    LOGGER.info(
        "Resumo final: %d enviada(s), %d erro(s), %d já vista(s), %d acima do limite.",
        enviados,
        erros,
        len(candidatas) - len(novas),
        len(restantes),
    )

    if not enviados and erros:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
