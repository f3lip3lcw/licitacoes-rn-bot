# Monitor de Licitações — DOE-RN

Bot em Python que consulta a API pública do **Diário Oficial do Estado do
Rio Grande do Norte** e manda no Telegram as publicações que parecem
oportunidade de licitação: aviso, edital, pregão, dispensa, chamamento público,
credenciamento.

O foco é a **SEAD**, incluindo a Coordenadoria de Compras Governamentais
(COMPR/SEAD). Roda no terminal quando você quiser e, se quiser, todo dia às
08h pelo GitHub Actions.

## Como funciona

O portal antigo (`diariooficial.rn.gov.br`) é ASP.NET WebForms e só tem busca
até 17/11/2022. O conteúdo atual está no SDOE, e a Busca Avançada de lá consome
uma API pública que devolve JSON e não exige login:

```
POST https://deirn.sdoe.com.br/diariooficial/public/search
GET  https://deirn.sdoe.com.br/diariooficial/public/busca-avancada/consultarMateriaBuscaAvancada
GET  https://deirn.sdoe.com.br/diariooficial/public/busca-avancada/consultarPublicacao
```

O bot não faz scraping de HTML — usa essa API. A data vai no campo
`intervaloAno`, no formato `DD/MM/AAAA-DD/MM/AAAA`, que é o que a própria
interface envia, apesar do nome.

O fluxo de uma execução:

1. Faz as consultas de `config.yaml`, já filtrando no servidor pela categoria
   **1164 (SEAD)**.
2. Une os resultados e deduplica pelo código da publicação (mantendo o texto
   mais completo) e por hash de conteúdo.
3. Classifica cada publicação pelo cabeçalho: `aviso de licitação`, `edital`,
   `pregão eletrônico` e afins passam; `extrato`, `termo aditivo`, `resultado`,
   `homologação` são descartados.
4. Consulta `.state/seen.json` e manda no Telegram só o que ainda não foi
   avisado.

## Estrutura

```
bot.py        entrada do programa
doe.py        cliente da API do SDOE
filters.py    classificação de oportunidade x ruído
state.py      o que já foi notificado
telegram.py   envio de mensagens e documentos
utils.py      limpeza e normalização de texto
config.yaml   consultas e filtros
tests/        testes (sem rede)
```

## Instalação

```bash
cd ~/licitacoes-rn-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python bot.py --dias 2 --dry-run            # só mostra, não envia
python bot.py --dias 2 --dry-run --debug    # + o motivo de cada filtro
python bot.py --dias 2                      # envia para o Telegram
python bot.py --data 22/10/2026 --dry-run   # um dia específico
python bot.py --orgao SEAD --dias 5 --dry-run
python bot.py --incluir-municipios --dias 2 --dry-run
python bot.py --test-telegram               # mensagem de teste
```

`--dias 2` cobre hoje e ontem, porque a publicação do DOE costuma sair durante
o dia. `--dry-run` não envia nada e não marca itens como vistos, então dá para
rodar à vontade.

O `.state/seen.json` é atualizado a cada envio: rodar várias vezes no mesmo dia
não repete licitação. Para forçar o reenvio de tudo:

```bash
rm .state/seen.json
python bot.py --dias 2
```

## Telegram

1. No Telegram, fale com **@BotFather**, envie `/newbot` e siga os passos. Ele
   devolve um token.
2. Envie `/start` para o seu bot e descubra o chat_id acessando
   `https://api.telegram.org/botSEU_TOKEN/getUpdates` — o id está em
   `"chat":{"id":...}`. Para grupo, adicione o bot e use o id negativo.
3. Copie `.env.example` para `.env` e preencha:

```dotenv
TELEGRAM_BOT_TOKEN=123456789:AAExemploDeTokenDoBotFather
TELEGRAM_CHAT_ID=8838749032
```

4. Teste com `python bot.py --test-telegram`.

O token é uma senha: o `.env` está no `.gitignore` e nunca deve entrar no Git.

## Rodando todo dia (GitHub Actions)

O workflow `.github/workflows/doe-rn.yml` roda o bot de segunda a sexta às
08h07 de Brasília, sem ligar o Mac e sem custo no plano gratuito. Ele executa
**os dois perfis** — `config.yaml` (SEAD geral) e `config-ti.yaml` (TI) — e o
estado compartilhado evita que a mesma publicação seja avisada duas vezes.
Depois disso, um passo separado sempre manda um **relatório no Telegram**, com
o resultado de cada perfil — inclusive quando não há novidade, para o silêncio
nunca virar dúvida. Já está configurado no repositório
`f3lip3lcw/licitacoes-rn-bot`. Para montar em outro lugar:

1. `git push` do código.
2. Cadastrar os segredos em **Settings → Secrets and variables → Actions**:
   `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
3. Em **Settings → Actions → General → Workflow permissions**, marcar
   **Read and write permissions**. Sem isso o workflow não salva o
   `.state/seen.json` e as licitações seriam reenviadas todo dia.
4. Testar pela aba **Actions → Monitor DOE-RN → Run workflow**. No disparo
   manual dá para escolher o perfil: `ambos` (padrão), `config.yaml` ou
   `config-ti.yaml`.

O horário é o cron, em UTC (Brasília é UTC-3):

```yaml
on:
  schedule:
    - cron: "7 11 * * 1-5"   # 11:07 UTC = 08:07 em Brasília, seg. a sex.
```

| Brasília | Cron |
|---|---|
| 07:07 | `7 10 * * 1-5` |
| 08:07 (atual) | `7 11 * * 1-5` |
| 09:07 | `7 12 * * 1-5` |

O minuto `7` em vez de `0` é de propósito: o início de cada hora é o pico do
GitHub Actions e o cron no `:00` chegou a atrasar 3 horas na fila. Fins de
semana ficaram de fora porque o DOE não publica.

**Relatório.** Todo dia útil, após os dois perfis, chega no Telegram uma
mensagem com o resultado (`Relatório DOE-RN — data`), mesmo que nada tenha
sido encontrado. Se nenhum perfil registrar execução (ou seja, os passos
falharam antes de gravar), a mensagem avisa isso explicitamente — o silêncio
nunca passa despercebido. Fora do fluxo, `python bot.py --relatorio` envia o
último resumo na hora.

Duas observações:

- O estado salvo no Actions é o do repositório. Se você rodar também no Mac,
  cada um tem o seu e a mesma publicação pode ser avisada duas vezes.
- Repositório parado por 60 dias tem o agendamento desativado pelo GitHub.
  Basta rodar uma vez manualmente pela aba Actions para reativar.

## Personalizando

Tudo em `config.yaml`.

**Perfis.** Além do `config.yaml` (SEAD geral), o repositório traz o
`config-ti.yaml`, que foca em tecnologia da informação — inclusive nas fases
antes do edital (ETP, minuta de termo de referência, pesquisa de preços,
consulta pública):

```bash
python bot.py --config config-ti.yaml --dias 2 --dry-run
```

No GitHub Actions, o input `config` do workflow escolhe o perfil. Para o
perfil TI rodar todo dia, troque o default em `.github/workflows/doe-rn.yml`
de `config.yaml` para `config-ti.yaml`.

**Consultas.** Cada item de `buscas` é uma consulta, e `codigoCategoria: 1164`
filtra no servidor pela SEAD. A API é tolerante a acentos (`licitação` =
`licitacao`). Cuidado com o limite de **100 requisições por hora**: com as 8
consultas do perfil geral o bot gasta ~8 por execução, e o perfil TI usa ~13 a
26.

**Assunto.** `termos_incluir` é um OR simples: basta um termo. Já
`regras_incluir` é uma lista de grupos, e **todos** os grupos precisam casar —
é o (A ou B) e (C ou D):

```yaml
filtros:
  regras_incluir:
    - ["pesquisa de preços", "consulta pública", "aviso de licitação"]
    - ["tecnologia da informação", "notebook", "computação em nuvem"]
```

A regra vale para o texto e o resumo. Termos curtos são armadilha: a busca é
por substring, então `API` casaria em "capital" e `SOC` em "sociedade" — use
termos compostos no lugar de siglas.

`termos_excluir` rejeita se o termo aparecer em qualquer lugar do texto:

```yaml
filtros:
  termos_incluir: ["software", "tecnologia da informacao"]
  termos_excluir: ["merenda escolar"]
```

Para duas frentes separadas, use dois `config.yaml`.

**PDF.** `telegram: anexar_pdf: true` envia o PDF como documento quando a
publicação tiver arquivo.

**Link direto.** Vem desligado (`links: direto: false`) porque custa 2 chamadas
extras por item; com desligado o bot manda o link da busca já preenchida, que
funciona. Se ligar, mantenha `max_diretos` baixo.

**Sobre "CA".** As publicações da SEAD usam "Coordenadoria de Compras
Governamentais (COMPR/SEAD)"; busca literal por `CA/SEAD` ou `Central de
Aquisições` retorna 0 resultados. Por isso o filtro é pela categoria 1164, não
pela sigla — e nunca vale checar `if 'CA' in texto`, que casa com "cada",
"cargo", "câmara" e afins.

## Testes

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Sem rede: cobrem o payload da busca, o rate limit (429 e 400), a deduplicação e
a classificação de casos reais (aviso, extrato, adjudicação, termo aditivo no
resumo, IRP, concurso público).

## Problemas comuns

**`HTTP 429` / `rate_limit_exceeded`** — a API responde com `retry_after_sec`.
Espera curta (até 120s) o bot aguenta; espera longa ele avisa e para. Se
acontecer sempre, reduza as `buscas`, mantenha `links.direto: false` e evite
rodar várias vezes seguidas — o bloqueio é por IP.

**`HTTP 400` na busca** — a data tem que ir em `intervaloAno` como
`DD/MM/AAAA-DD/MM/AAAA`; `dataInicial`/`dataFinal` são ignorados pela API.

**Sem resultado** — o DOE pode não ter publicado. Teste `--dias 7 --dry-run` e
compare com a Busca Avançada oficial. `--debug` mostra o motivo de cada item
ignorado.

**Telegram `401`** — token inválido; gere outro no BotFather.
**Telegram `400: chat not found`** — chat_id errado, ou o bot não recebeu
`/start`.

**Workflow não roda** — confira os segredos, a permissão de escrita do
workflow, e lembre que `schedule` só vale no branch padrão (`main`) e em UTC.

## Limites

- A API do SDOE é pública, mas não documentada; pode mudar. O ajuste fica
  concentrado em `doe.py`.
- O bot é triagem, não parecer: leia o edital antes de qualquer decisão.
- Dados públicos; use apenas para acompanhar licitações.
