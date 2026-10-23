# Monitor de Licitações — DOE-RN

Bot em Python que consulta o **Diário Oficial do Estado do Rio Grande do Norte**
e envia no Telegram as publicações que parecem ser oportunidades de licitação
(aviso, edital, pregão, dispensa, chamamento, credenciamento etc.).

Ele foi feito para rodar de graça no **GitHub Actions**, uma vez por dia, sem
precisar deixar o computador ligado.

---

## 1. O que mudou em relação ao exemplo do Gemini

O exemplo original usava `requests` + `BeautifulSoup` e procurava
`<div class="resultado-item">` no portal. Essa classe não existe no DOE-RN.

O portal antigo (`diariooficial.rn.gov.br`) é ASP.NET WebForms e só tem busca
até **17/11/2022**. A busca atual fica no SDOE:

```
https://deirn.sdoe.com.br/diariooficialweb/#/busca-avancada?diario=MTIx
```

O SPA do SDOE consome uma API pública que devolve **JSON** e não exige login:

```
POST https://deirn.sdoe.com.br/diariooficial/public/search
GET  https://deirn.sdoe.com.br/diariooficial/public/busca-avancada/consultarMateriaBuscaAvancada
GET  https://deirn.sdoe.com.br/diariooficial/public/busca-avancada/consultarPublicacao
```

Por isso este bot **não faz scraping de HTML**: ele usa a mesma API da busca
oficial. É mais rápido, mais estável e não quebra quando o layout muda.

O campo de data da API é `intervaloAno`, no formato
`DD/MM/AAAA-DD/MM/AAAA`. O exemplo do Gemini não tinha isso.

### 1.1. Por que o script do Gemini não funciona

O script `monitor_doe.py` sugerido tem problemas que impedem o funcionamento:

1. **Faz `GET` na página de busca sem parâmetros.** O `Search.aspx` é um
   formulário ASP.NET: sem enviar data/palavra e sem o `__VIEWSTATE`, ele
   devolve apenas o formulário vazio, não os resultados do dia.
2. **O portal antigo só pesquisa até 17/11/2022.** Mesmo preenchendo o
   formulário, não há publicações atuais ali.
3. **Não usa a data em lugar nenhum.** `DATA_HOJE` só aparece na mensagem; a
   requisição não filtra por data.
4. **`"CA"` e `"UST"` são sensíveis a maiúsculas/minúsculas e muito amplos.**
   `"CA"` casa com “cada”, “cargo”, “câmara” etc.; `"UST"` pode não aparecer
   no texto e não é um termo oficial de licitação.
5. **Não tem deduplicação.** O mesmo aviso seria reenviado todos os dias.
6. **Markdown do Telegram quebra fácil.** Um `*` ou `_` no texto da publicação
   gera `HTTP 400`; é preciso escapar (este bot usa HTML com escape).
7. **Token hardcoded no código.** Se o arquivo for para o GitHub, o token do
   bot vaza. Aqui o token vai em secrets/`.env`.
8. **Não verifica `resposta.ok` nem faz retry.** Falhas do Telegram passam
   silenciosamente.
9. **Workflow desatualizado e sem persistência de estado.** `checkout@v3` e
   `setup-python@v4` são antigos, e não há commit do estado entre execuções.

A parte aproveitável da sugestão são as **palavras-chave** (software,
tecnologia da informação etc.). Elas podem ser usadas como filtro de assunto
em `config.yaml` — veja a seção 6.3 —, mas não como critério de scraping.

---

## 2. Estrutura do projeto

```
licitacoes-rn-bot/
├── bot.py                     # entrada do programa / CLI
├── doe.py                     # cliente da API pública do SDOE
├── filters.py                 # classificação de oportunidades x ruído
├── state.py                   # estado persistente (deduplicação)
├── telegram.py                # envio de mensagens/documentos
├── utils.py                   # limpeza/normalização de texto
├── config.yaml                # consultas e filtros
├── requirements.txt
├── .env.example               # modelo das variáveis do Telegram
├── .github/workflows/doe-rn.yml
├── .state/seen.json           # estado inicial (comitado no repositório)
└── tests/
    ├── test_doe.py            # cliente da API, rate limit e payload
    └── test_filters.py        # classificação de oportunidades x ruído
```

---

## 3. Rodar localmente (macOS)

### 3.1. Criar o ambiente virtual

```bash
cd ~/licitacoes-rn-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2. Testar sem Telegram

```bash
python bot.py --data 23/10/2026 --dry-run
```

O `--dry-run` imprime as mensagens no terminal, não envia nada e não marca
itens como vistos. Para varrer os últimos dias:

```bash
python bot.py --dias 2 --dry-run
```

Para ver o motivo de cada item ter sido aceito ou ignorado:

```bash
python bot.py --dias 2 --dry-run --debug
```

### 3.3. Rodar só a SEAD

```bash
python bot.py --orgao SEAD --dias 5 --dry-run
```

### 3.4. Incluir prefeituras e câmaras

Por padrão o bot foca no Estado e exclui `Prefeituras e Câmaras Municipais` e
`Publicações Particulares`. Para incluir:

```bash
python bot.py --incluir-municipios --dias 2 --dry-run
```

### 3.5. Rodar sem dry-run (depois de configurar o Telegram)

```bash
python bot.py --dias 2
```

---

## 4. Configurar o Telegram (tarefa manual)

### 4.1. Criar o bot

1. Abra o Telegram e procure **@BotFather**.
2. Envie `/newbot`.
3. Escolha um nome (ex.: `Licitações RN`) e um usuário terminado em `bot`
   (ex.: `licitacoes_rn_bot`).
4. O BotFather devolve um token parecido com:
   `123456789:AAExemploDeTokenDoBotFather`.
5. **Não compartilhe esse token e não comite no Git.**

### 4.2. Descobrir o chat_id

1. Abra uma conversa com o seu bot e envie qualquer mensagem (`/start`).
2. No navegador, acesse:

   ```
   https://api.telegram.org/botSEU_TOKEN/getUpdates
   ```

3. Procure `"chat":{"id":...}`. Esse número é o `TELEGRAM_CHAT_ID`.
4. Se for um grupo, adicione o bot ao grupo, envie uma mensagem e use o `id`
   negativo que aparecer (ex.: `-1001234567890`).

Alternativa: use o bot **@userinfobot** para ver seu ID.

### 4.3. Preencher o `.env`

```bash
cd ~/licitacoes-rn-bot
cp .env.example .env
```

Edite o `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=123456789:AAExemploDeTokenDoBotFather
TELEGRAM_CHAT_ID=123456789
# TELEGRAM_THREAD_ID=123   # opcional, para grupos com tópicos
```

### 4.4. Testar o Telegram

```bash
python bot.py --test-telegram
```

Se chegar a mensagem `Bot DOE-RN configurado com sucesso`, está pronto.

---

## 5. Colocar no GitHub Actions (tarefa manual)

### 5.1. Criar o repositório

Recomendo um repositório **privado** (o token não vai para o Git, mas é mais
seguro). No GitHub, crie `licitacoes-rn-bot` sem README.

No terminal:

```bash
cd ~/licitacoes-rn-bot
git init
git add .
git commit -m "Bot de licitações do DOE-RN"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/licitacoes-rn-bot.git
git push -u origin main
```

Se tiver o GitHub CLI autenticado:

```bash
gh repo create licitacoes-rn-bot --private --source=. --remote=origin --push
```

### 5.2. Cadastrar os secrets

No repositório:

1. **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = token do BotFather
   - `TELEGRAM_CHAT_ID` = seu chat_id
   - opcional: `TELEGRAM_THREAD_ID`
3. Salve.

### 5.3. Rodar manualmente para testar

1. Aba **Actions**.
2. Selecione **Monitor DOE-RN**.
3. **Run workflow** → branch `main` → `dias` = `2` → **Run workflow**.
4. Abra o log e confira se apareceu `Notificada ...` e se a mensagem chegou
   no Telegram.

### 5.4. Agendar

O workflow já tem:

```yaml
on:
  schedule:
    - cron: "0 11 * * 1-5"
```

O GitHub usa UTC: **11:00 UTC = 08:00 em America/Sao_Paulo** (UTC-3).
Isso roda de segunda a sexta.

Para mudar o horário, edite `.github/workflows/doe-rn.yml`, faça commit e push.
Exemplos:

| Horário em Brasília | Cron UTC |
|---|---|
| 07:00 | `0 10 * * 1-5` |
| 08:00 | `0 11 * * 1-5` |
| 09:00 | `0 12 * * 1-5` |
| Todos os dias 08:00 | `0 11 * * *` |

### 5.5. Estado e notificações repetidas

O arquivo `.state/seen.json` guarda os códigos já notificados. O workflow faz
commit desse arquivo depois de cada execução, para não repetir a mesma
licitação no dia seguinte.

O workflow já pede permissão de escrita:

```yaml
permissions:
  contents: write
```

Se o `git push` falhar no Actions, verifique:

- **Settings** → **Actions** → **General** → **Workflow permissions**:
  marque **Read and write permissions**.
- Proteção de branch: se `main` estiver protegida contra push direto, o bot
  não consegue salvar o estado. Nesse caso, remova a proteção ou use um
  repositório/branch separado só para o estado.

---

## 6. Personalizar as buscas

Tudo fica em `config.yaml`.

### 6.1. Consultas

Cada item de `buscas` é uma consulta independente. O bot junta os resultados
e remove duplicados.

```yaml
buscas:
  - palavras: "licitação"
    codigoCategoria: 1164
  - palavras: "pregão eletrônico"
    codigoCategoria: 1164
  - palavras: "registro de preços"
    codigoCategoria: 1164
  - palavras: "dispensa"
    codigoCategoria: 1164
  - palavras: "credenciamento"
    codigoCategoria: 1164
  - palavras: "chamamento público"
    codigoCategoria: 1164
  - palavras: "coordenadoria de compras"
    codigoCategoria: 1164
  - palavras: "concorrência"
    codigoCategoria: 1164
```

`codigoCategoria: 1164` é a categoria **Secretaria de Estado da Administração
- SEAD** no DOE-RN. O filtro é aplicado no servidor, então a busca já volta
só com publicações da SEAD — inclusive as da **Central de Aquisições /
Coordenadoria de Compras Governamentais (COMPR/SEAD)**.

A API é tolerante a acentos: `licitação` e `licitacao` retornam o mesmo
resultado. Prefira frases específicas para reduzir ruído.

> **Limite da API:** são **100 requisições por hora**. Cada consulta gasta 1
> requisição (2 se precisar paginar). Com 8 consultas, o bot usa ~8 a 16 por
> execução, bem abaixo do limite. Evite adicionar dezenas de buscas ou rodar o
> bot várias vezes seguidas. Se a API responder `429`, o bot lê o
> `retry_after_sec`: espera se for pouco tempo e aborta com mensagem clara se o
> bloqueio for longo.

### 6.2. Foco na SEAD

O `config.yaml` já vem com:

```yaml
filtros:
  categorias_incluir:
    - "Secretaria de Estado da Administração - SEAD"
```

Isso funciona como uma segunda barreira: mesmo que alguma consulta traga
resultado de outro órgão, ele é descartado. Para monitorar **todas** as
secretarias, apague essa linha e remova os `codigoCategoria` das buscas.

Para testar só a SEAD pela linha de comando:

```bash
python bot.py --orgao SEAD --dias 5 --dry-run
```

> **Sobre “CA”:** em setembro/outubro de 2026 as publicações da SEAD usam
> **“Coordenadoria de Compras Governamentais (COMPR/SEAD)”** e **“CPA/SEAD”**;
> a busca literal por `CA/SEAD` ou `Central de Aquisições` retorna **0**
> resultados. Por isso o bot filtra pela **categoria 1164**, não pela sigla.
> Também não use `if 'CA' in texto`: isso casa com “cada”, “cargo”, “câmara”
> etc.

### 6.3. Filtrar por assunto

Exemplos:

```yaml
filtros:
  termos_incluir:
    - "medicamento"
    - "material hospitalar"
  termos_excluir:
    - "merenda escolar"
    - "publicidade"
```

`termos_incluir` exige pelo menos um termo. `termos_excluir` rejeita se
qualquer termo aparecer no texto.

Se o foco for tecnologia (a intenção por trás das palavras `UST`/`SOFTWARE` do
script do Gemini), dá para combinar:

```yaml
filtros:
  termos_incluir:
    - "software"
    - "tecnologia da informacao"
    - "licenca de uso"
    - "computador"
    - "datacenter"
```

Cuidado: isso restringe **todas** as buscas e pode deixar de fora licitações
de outros assuntos. Para receber tudo e só destacar tecnologia, o melhor é
manter `termos_incluir: []` e criar uma segunda execução com outro
`config.yaml`.

### 6.4. Receber o PDF

```yaml
telegram:
  anexar_pdf: true
```

Quando a publicação tem arquivo, o bot envia o PDF como documento, com a
legenda contendo órgão, data, título e links. Se não tiver PDF, envia texto.

### 6.5. Limite de mensagens

```yaml
telegram:
  limite_notificacoes: 20
```

Se houver mais oportunidades do que o limite, o bot envia um aviso
`Mais X oportunidade(s) encontradas...`. Aumente o limite ou refine os filtros.

### 6.6. Link direto

O link direto da publicação exige **duas chamadas extras por item** (primeiro
para descobrir `codigoPublicacao`/`codigoCliente`, depois para obter
`idMateriaArquivo`). Por causa do limite de 100 requisições/hora, ele vem
**desligado** por padrão:

```yaml
links:
  direto: false
  max_diretos: 5
```

Com `direto: false`, o bot envia o link da busca já preenchida (que funciona
bem e não gasta requisições extras). Se quiser ligar, use um `max_diretos`
baixo:

```yaml
links:
  direto: true
  max_diretos: 5
```

Se a resolução falhar, o bot mantém o link da busca.

---

## 7. Como o bot decide o que é oportunidade

Ele olha o começo do texto (cabeçalho) e:

- **Aceita** termos como `aviso de licitação`, `aviso de abertura`, `edital`,
  `pregão eletrônico`, `dispensa eletrônica`, `chamamento público`,
  `credenciamento`, `seleção pública`, `manifestação de interesse`,
  `intenção de registro de preços`, `concorrência`, `leilão`, `convoca`.
- **Rejeita** cabeçalhos como `extrato`, `termo aditivo`, `resultado`,
  `homologação`, `adjudicação`, `julgamento`, `ata de registro`, `portaria`,
  `sanção`, `impugnação`, `revogação`, `suspensão`, `errata`, `retificação`.
- Remove categorias de prefeituras/câmaras e publicações particulares por
  padrão.

Isso não é perfeito: sempre confira a publicação oficial antes de participar.
O bot é um filtro de triagem, não um parecer jurídico.

---

## 8. Rodar os testes

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Os testes não acessam a internet; cobrem normalização, extração de título,
classificação de casos reais (aviso, extrato, adjudicação, SEAD etc.) e o
tratamento de `429`, `400` e do payload de busca.

---

## 9. Solução de problemas

### `ModuleNotFoundError: No module named 'requests'`

Ative o ambiente virtual e instale as dependências:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### `HTTP 400` na busca

A API é sensível ao formato de data. O bot envia:

```json
"intervaloAno": "23/10/2026-23/10/2026"
```

Não troque por `2026-10-23` nem acrescente `dataInicial`/`dataFinal` com outro
formato. Se você editar `doe.py`, mantenha esse padrão.

### `HTTP 429` / `rate_limit_exceeded`

A API permite **100 requisições por hora**. O erro traz algo como:

```json
{"error":"rate_limit_exceeded","limit":100,"window_sec":3600,"retry_after_sec":2765}
```

O bot entende esse JSON:

- espera e tenta de novo se `retry_after_sec` for curto (até 120 s);
- aborta a execução com mensagem clara se for longo, em vez de ficar quase uma
  hora dormindo.

Se acontecer com frequência, reduza `buscas` no `config.yaml`, mantenha
`links.direto: false` e evite rodar o bot várias vezes em sequência. O bloqueio
é por IP/rede, então testes manuais também contam.

### Nenhum resultado

- O DOE pode não ter publicado no dia. Teste uma janela maior:
  `python bot.py --dias 7 --dry-run`.
- Confira a busca oficial:
  `https://deirn.sdoe.com.br/diariooficialweb/#/busca-avancada?diario=MTIx`
- Rode com `--debug` para ver os itens ignorados e o motivo.

### Telegram `HTTP 401 Unauthorized`

Token inválido. Gere outro no BotFather e atualize o secret/`.env`.

### Telegram `HTTP 400 Bad Request: chat not found`

O `chat_id` está errado ou você não enviou `/start` para o bot. Se for grupo,
o bot precisa estar no grupo e o `chat_id` é negativo.

### O workflow não roda no horário

- GitHub Actions só executa `schedule` no branch padrão (`main`).
- O cron é UTC.
- Execuções agendadas podem atrasar alguns minutos.
- Repositórios sem atividade por 60 dias podem ter os workflows agendados
  desativados; rode manualmente ou faça um commit para reativar.

### O `git push` do estado falha

Veja a seção 5.5 (permissões e proteção de branch).

---

## 10. Segurança e limites

- **Nunca comite o `.env`**. Ele já está no `.gitignore`.
- Prefira repositório privado.
- O token do Telegram dá controle do bot; trate como senha.
- A API do SDOE é pública, mas não documentada oficialmente. Ela pode mudar.
  Se isso acontecer, o ajuste fica concentrado em `doe.py`.
- A API permite **100 requisições por hora**. O bot espera 1 s entre chamadas,
  usa no máximo 2 páginas por consulta e vem com o link direto desligado para
  não estourar o limite.
- Os dados são públicos; use apenas para acompanhar licitações.
- O bot não substitui a leitura do edital nem a análise jurídica.

---

## 11. Checklist manual

- [ ] Criar o bot no **@BotFather** e copiar o token.
- [ ] Enviar `/start` para o bot e descobrir o `chat_id`.
- [ ] Preencher o `.env` com token e chat_id.
- [ ] Rodar `python bot.py --test-telegram`.
- [ ] Rodar `python bot.py --dias 2 --dry-run` e conferir a saída.
- [ ] Criar o repositório no GitHub (privado).
- [ ] Fazer `git push`.
- [ ] Cadastrar `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` nos secrets.
- [ ] Rodar o workflow manualmente com `dias=2`.
- [ ] Confirmar a mensagem no Telegram.
- [ ] Ajustar `config.yaml` (SEAD, termos, limite, PDF).
- [ ] Confirmar o horário do cron (UTC) e o branch padrão.
- [ ] Verificar se o workflow consegue fazer push do `.state/seen.json`.
