# Arquitetura

## Visão geral

O projeto é dividido em dois pacotes com uma regra rígida entre eles:

- **`acervo/`** — o domínio: modelos, parsers, persistência e serviços.
  Não importa Streamlit em lugar nenhum. Tudo aqui é testável sem UI.
- **`app/`** — a interface Streamlit: só apresentação. Toda lógica de dados
  chega através dos serviços de `acervo/search/`, e toda decisão de acesso
  através de `acervo/auth/`.

Os scripts de `scripts/` são CLIs finos: parseiam argumentos, chamam um
serviço e imprimem o resultado.

```
UI (app/paginas/*)         CLI (scripts/*)
        │                        │
        └──────────┬─────────────┘
                   ▼
   serviços (acervo/search/* e acervo/auth/*)  ← validação, orquestração, fronteira de erro
                   │
      ┌────────────┼────────────────┐
      ▼            ▼                ▼
 ingestion/    persistence/     core/models
 (scanner +    (db.py pool +    (dataclasses
  parsers)      repository)      imutáveis)
                   │
                   ▼
            PostgreSQL (Neon)
```

## Camadas, de baixo para cima

### `acervo/core` — modelos e exceções

- `models.py`: dataclasses **frozen** (imutáveis) que representam o que existe
  no banco (`Categoria`, `Arquivo`, `Bloco`) e o que a busca devolve
  (`ResultadoBusca`, `PaginaBusca`, `ResumoAcervo`). Sem I/O, sem métodos de
  negócio. `Arquivo.origem` distingue `'varredura'` (indexação em lote do
  disco) de `'upload'` (enviado pela interface) — essa distinção é a base da
  segurança da limpeza de órfãos.
- `exceptions.py`: hierarquia única com raiz `AcervoError`. **Toda falha
  esperada vira uma dessas classes**, nunca uma exceção crua:
  - `ConfiguracaoError` — .env ou categorias.json ausente/inválido (fatal);
  - `ConexaoBancoError` — driver/rede (o chamador nunca vê psycopg);
  - `ArquivoParseError` — arquivo ilegível; carrega `caminho`, `etapa` (nome
    do parser) e `causa` para o registro de falhas;
  - `BuscaError` — a única exceção que a UI de busca precisa conhecer;
  - `UploadError` — idem para a página Adicionar;
  - `CadastroError` — dados de cadastro/troca de senha recusados; a mensagem
    é sempre segura para exibir (existe para dizer o que corrigir no formulário);
  - `AutenticacaoError` — login recusado. **Cuidado ao mexer nas mensagens**:
    elas vão para uma tela pública e não podem revelar se um e-mail existe;
  - `PermissaoError` — ação administrativa não permitida.

  `Usuario` (em `models.py`) segue a mesma regra dos outros dataclasses, com
  uma omissão deliberada: **não tem o hash da senha**. Ele só trafega entre o
  repositório e `acervo/auth`, então nenhum objeto que chega à interface (ou
  a um log, ou ao `session_state`) carrega credencial.

### `acervo/ingestion` — extração de conteúdo

- `scanner.py`: varre as pastas raiz listadas em `config/categorias.json`
  (relativas à raiz do projeto), ignora as pastas do próprio projeto
  (`PASTAS_IGNORADAS`) e emite um `ArquivoBruto` por arquivo: caminho
  relativo com `/`, pasta raiz, extensão, tamanho, **hash SHA-256 do
  conteúdo** e qual parser é responsável (`EXTENSOES_PARSERS`). Falha ao ler
  um arquivo individual é logada e o arquivo é pulado — a varredura nunca
  cai inteira.
- `parsers/`: um módulo por formato, todos com o mesmo contrato
  (`base.Parser`): `parse(caminho: Path) -> list[BlocoBruto]`, levantando
  `ArquivoParseError` (nunca exceção crua) quando o arquivo não abre.
  Um `BlocoBruto` tem `ordem, titulo, explicacao, codigo, linguagem`.

  | Parser              | Estratégia de blocos                                                        |
  |---------------------|------------------------------------------------------------------------------|
  | `notebook_parser`   | Cada célula de código = 1 bloco; a célula markdown anterior vira a explicação. Detecta `%%sql` para linguagem. |
  | `sql_parser`        | Blocos separados por linha em branco; comentários `--` viram explicação. Tenta utf-8 e cai para latin-1. |
  | `text_parser`       | Arquivo inteiro = 1 bloco. `.md` vira explicação (texto); `.py/.js/.txt` viram código. |
  | `pdf_parser`        | 1 bloco por página ("Página N"); página corrompida é pulada com log, sem derrubar o PDF. |
  | `pptx_parser`       | 1 bloco por slide ("Slide N"), concatenando os text frames.                  |

### `acervo/persistence` — banco

- `db.py`: um único `ConnectionPool` por processo (psycopg_pool, 1–5
  conexões). `cursor()` é um context manager que dá commit no sucesso,
  rollback no erro, devolve a conexão ao pool sempre, e converte
  `psycopg.Error` em `ConexaoBancoError`. Obter conexão tem **retry com
  backoff (3 tentativas)** porque o Neon serverless tem cold start e derruba
  conexões ociosas. Uma vez executando comandos, não há retry automático
  (a operação pode ter tido efeito parcial).
- `repository.py`: **a única camada que conhece SQL.** Cada método recebe o
  cursor aberto (`cur`) — quem controla a fronteira da transação é o
  chamador. Ex.: o indexador faz upsert do arquivo + troca de blocos dentro
  de um único `with cursor()`, então falha no meio desfaz aquele arquivo
  inteiro sem afetar os demais. O nome do schema é interpolado por f-string
  (seguro: valor fixo do código, nunca input do usuário); valores de coluna
  vão sempre como parâmetro `%s`.

### `acervo/search` — serviços (a porta de entrada)

Tudo que UI e CLI chamam vive aqui. Todos os serviços aceitam repositórios
injetáveis (kwargs opcionais) — é assim que os testes unitários usam fakes
em memória.

- **`indexador_service.indexar_tudo()`** — indexação em lote. Contrato de
  robustez: a falha de UM arquivo (parser, encoding, erro de banco naquele
  arquivo) é isolada, logada, registrada em `falhas_indexacao`, e o lote
  segue. Só erro de configuração é fatal. Fluxo por arquivo:
  1. `hash_ja_indexado(caminho, hash)`? → pula (`pulados_sem_alteracao`);
  2. parseia **fora de transação** (parte lenta, não segura conexão do pool);
  3. numa transação: upsert do arquivo → apaga blocos antigos → insere os
     novos (com `_sanitizar_texto`: remove `\x00`, trunca em 50.000 chars por
     campo — limite do tsvector).
- **`upload_service.adicionar_conteudo(nome, bytes, categoria)`** — o
  caminho da página Adicionar. O arquivo não existe no disco do projeto: os
  bytes vão para um temporário só durante o parse, e o registro entra com
  `origem='upload'` e caminho lógico `uploads/<pasta_raiz>/<nome>`. Regras de
  duplicata, na ordem: mesmo caminho+hash → `sem_alteracao`; mesmo hash em
  outro caminho → `duplicado` (não regrava); mesmo caminho com hash novo →
  `atualizado` (troca os blocos); senão → `adicionado`.
  `criar_categoria()` gera `pasta_raiz` sintética `upload_<slug>` — nunca
  colide com pastas reais nem entra na varredura/limpeza.
- **`limpeza_service.limpar_orfaos()`** — reconcilia banco × disco com duas
  salvaguardas deliberadas (o fluxo do dono é apagar pastas já indexadas):
  1. pasta raiz **inteira ausente** do disco → registros preservados
     ("conteúdo arquivado no banco", nunca "conteúdo a apagar");
  2. `origem='upload'` nunca entra na reconciliação (filtro no repositório).
  Só vira órfão o arquivo sumido de dentro de pasta que ainda existe (rename,
  reorganização). Dry-run por padrão; remoção só com `aplicar=True`.
- **`busca_service.buscar()`** — valida input (termo vazio, modo, paginação),
  traduz página→limite/offset, escolhe a variante (`texto` full-text /
  `codigo` ILIKE+trigram) e converte qualquer erro em `BuscaError`.
- **`estatisticas_service.resumo_do_acervo()`** — números agregados para o
  dashboard.

### `acervo/auth` — quem entra (Fase 4)

Mesmo formato dos serviços de busca (repositório injetável, exceções da
hierarquia `AcervoError`), separado em pacote próprio porque a natureza do
que ele decide é outra.

- **`senhas.py`** — regras puras de credencial, sem I/O nenhum: hash e
  verificação **Argon2id** (m=19 MiB, t=2, p=1 — o piso do OWASP; o padrão de
  64 MiB da biblioteca triplicaria o pico de memória de cada login),
  normalização de e-mail, força mínima de senha (`MIN_SENHA`) e geração da
  senha temporária. Dois detalhes que existem por um motivo:
  - `hash_dummy` — verificação falsa executada quando o e-mail não existe,
    para que "e-mail inexistente" e "senha errada" custem o mesmo tempo;
  - `precisa_rehash` — hashes antigos se atualizam sozinhos no próximo login
    quando os parâmetros do Argon2 sobem, então endurecer os números depois
    é seguro.
- **`auth_service.py`** — `cadastrar`, `autenticar`, `alterar_senha`. Duas
  regras atravessam o módulo: (1) a tela de login não pode virar oráculo de
  e-mails cadastrados — o motivo real da recusa ("aguardando aprovação",
  "bloqueado") só é revelado **depois** de a senha ser conferida como
  correta; (2) o hash é lido, usado e descartado dentro da função.
- **`admin_service.py`** — `listar_usuarios`, `aprovar`, `recusar`,
  `bloquear`, `reativar`, `definir_papel`, `resetar_senha`. Toda função
  recebe o `ator` e tem quatro salvaguardas:
  1. **o poder do ator é reconferido no banco a cada ação** — a sessão da UI
     é uma fotografia do login e não expira enquanto a aba estiver aberta;
  2. **ninguém se derruba sozinho** (não dá para se bloquear nem se rebaixar);
  3. **sempre resta um administrador ativo**;
  4. **nada é apagado** — recusar e bloquear são status.

  `resetar_senha` devolve `(usuario, senha_em_claro)`. A senha em claro só
  existe nesse retorno; o banco guarda o hash e liga `senha_temporaria`.

### `acervo/voz` — gramática do assistente de voz

`comandos.py` traduz uma frase em português para um `Comando(acao, valor,
descricao)`. É uma camada pura: não conhece Streamlit, microfone nem banco —
recebe texto e devolve *o que fazer*.

O vocabulário é **fechado**: frase que não casa com nenhuma regra vira `None`,
e a interface responde "não entendi". Chutar a ação mais provável seria pior
que não fazer nada, porque quem depende de voz não tem como desfazer rápido.
Pela mesma razão, encerrar sessão exige frase inteira ("encerrar sessão"), não
a palavra "sair" — que aparece em qualquer conversa perto do microfone.

`escolher_opcao()` casa o que foi dito com uma opção que existe de verdade
("databriks" → "Databricks · Módulo 1"), numa escada que vai do exato ao
aproximado. Ela é necessária porque escrever no `session_state` um valor fora
da lista de um `selectbox` derruba a página inteira.

## Interface (`app/`)

### O portão de acesso

`streamlit_app.py` decide qual das três telas aparece, e elas são exclusivas:

```
sem sessão               -> paginas/login.py
senha_temporaria = True  -> paginas/trocar_senha.py (obrigatoria=True)
autenticado              -> navbar + páginas
```

O estado do meio existe porque a senha gerada por um admin circulou por fora
do sistema (foi ditada, colada numa mensagem) e não pode virar a senha
permanente de ninguém.

`sessao.py` guarda quem está logado no `session_state`, **só em memória**:
recarregar a página desloga, porque o Streamlit descarta o `session_state` a
cada conexão nova. Foi escolha — manter login entre recargas exigiria cookie
assinado, e com ele viriam segredo, expiração e revogação para administrar.
A consequência que o resto do código respeita: o `Usuario` de lá é uma
fotografia do momento do login e serve para desenhar a tela, **nunca para
autorizar uma ação** — quem decide permissão é o banco, relido a cada
operação em `admin_service`. O módulo também traz o freio de tentativas de
login (5 falhas → 60 s), que é conveniência contra chute manual, não defesa
contra ataque automatizado (o que segura força bruta é o custo do Argon2).


- `streamlit_app.py`: `set_page_config` + tema + o portão descrito acima +
  navbar própria (`st.segmented_control`) que roteia para `busca`,
  `dashboard`, `adicionar` e — só para admins — `usuarios`. O menu da conta
  (popover com o primeiro nome) leva à troca de senha voluntária e ao logout.
  Captura `ConfiguracaoError`/`AcervoError` e mostra erro amigável.
- `tema.py`: paleta exportada (constantes usadas também nos gráficos Altair)
  e CSS injetado uma vez. **Atenção**: o override global de fonte exclui os
  ícones do Streamlit (`stIconMaterial` precisa da fonte Material Symbols —
  sem a exceção, ícones viram texto tipo "arrow_right").
- `componentes.py`: helpers **puros** (resumir, formatar_numero,
  total_de_paginas, rotulo_categoria, previa_de_codigo, opcoes_de_navegacao,
  primeiro_nome, formatar_data) — são esses que os testes unitários cobrem —
  e componentes com `st.*` (card de resultado, paginação por callbacks em
  `session_state`).
- `paginas/busca.py`: fluxo reativo; consultas com `@st.cache_data`
  (TTL 5–10 min); mudança de parâmetros volta à página 1; diálogo
  (`st.dialog`) para o arquivo completo.
- `paginas/dashboard.py`: cartões de métrica + gráfico Altair horizontal por
  categoria (cores vindas do banco).
- `paginas/adicionar.py`: uploader multi-arquivo (extensões vindas de
  `upload_service.extensoes_aceitas()`), seleção/criação de categoria, um
  resultado por arquivo (erro em um arquivo não interrompe os demais) e
  `st.cache_data.clear()` após gravar — o conteúdo novo aparece na busca
  imediatamente.
- `paginas/login.py`: entrar e criar conta. Única página visível sem sessão,
  então tudo ali vale como texto público — as frases vêm prontas do
  `auth_service`, que é onde a regra de não revelar cadastros é testada.
- `paginas/trocar_senha.py`: serve à troca voluntária e à obrigatória
  (`obrigatoria=True`), que muda os rótulos e o texto explicativo.
- `paginas/usuarios.py`: painel do admin. Uma consulta (`listar_usuarios`)
  agrupada em três abas — Pendentes (com contagem) / Ativos / Recusados e
  bloqueados — e os botões possíveis a partir de cada status. A senha
  temporária de um reset aparece **uma vez**, sobrevive ao rerun via
  `session_state` e some no F5. Ações sobre a própria conta não são
  desenhadas: são exatamente as que o serviço barra.

### `app/voz.py` — o assistente executa escrevendo estado, não clicando

O assistente **não simula clique**. Em Streamlit o botão não existe entre um
rerun e outro: ele é redesenhado a cada execução do script, e o que faz de
verdade é escrever no `session_state`. Então `app/voz.py` pula a intermediação
e escreve o estado direto — o efeito na tela é idêntico ao do clique, e não
depende de achar um elemento no DOM.

Isso amarra uma regra de ordem em `streamlit_app.py`:
`voz.processar_pendente()` roda **antes** da navbar e das páginas. Depois que
um widget é instanciado, escrever na chave dele já não muda a tela desta
rodada.

O caminho de uma frase:

```
microfone (Web Speech API, no navegador)
  → controlador JS injetado na página principal
  → campo de texto do Streamlit  ──── (também aceita digitação)
  → callback guarda em `voz_pendente`
  → rerun → processar_pendente() interpreta e executa
```

Dois detalhes que parecem gambiarra e não são:

- **O controlador vive na página, não no iframe.** `st.iframe` cria um iframe
  novo a cada rerun; um reconhecimento de fala que morasse lá dentro morreria
  a cada comando executado. O iframe é só um instalador — nas vezes seguintes
  apenas reencaixa o botão no lugar que o Streamlit acabou de redesenhar.
- **O campo de texto no meio do caminho** é a única via de um script do
  navegador devolver texto ao Python sem construir um componente React com
  build próprio. Ele é também a interface de reserva: os mesmos comandos
  funcionam digitados, o que mantém o assistente utilizável em navegador sem
  reconhecimento de fala (Firefox) e testável sem microfone.

O contrato com as páginas é pequeno e está todo declarado no topo de
`app/voz.py`: as chaves de widget que o assistente pilota. Se uma página
renomear a sua, o assistente para de funcionar em silêncio — essa lista é o
primeiro lugar onde procurar.

## Decisões de projeto (o porquê)

1. **Banco como fonte da verdade.** As pastas de curso podem (e devem) ser
   removidas do disco após indexadas; a coluna `origem` + as salvaguardas da
   limpeza tornam isso seguro.
2. **Idempotência por hash.** Reindexar custa quase nada: SHA-256 igual =
   pula. Modificou = reprocessa e substitui os blocos (nunca duplica).
3. **Falha isolada por arquivo.** Um acervo de centenas de arquivos reais
   sempre tem um corrompido; ele nunca pode derrubar o lote (tabela
   `falhas_indexacao` é o registro de quem investigar).
4. **Repositórios recebem `cur`.** A fronteira transacional pertence ao
   serviço, não ao repositório — permite agrupar operações atomicamente.
5. **Serviços com repositórios injetáveis.** Testes unitários rodam com
   fakes em memória; os de integração usam schema descartável no Neon real.
6. **Dataclasses frozen.** Compatíveis com `st.cache_data` (serializáveis) e
   imunes a mutação acidental entre camadas.
7. **Permissão é decidida no serviço, não na tela.** Esconder um botão é
   conveniência visual; a barreira está em `admin_service`, que relê o papel
   do ator no banco a cada ação. A interface pode estar desatualizada — a
   sessão não expira enquanto a aba fica aberta — e isso é aceitável
   justamente porque ela não autoriza nada.
8. **Cadastro é auto-serviço, acesso não.** Qualquer um cria conta; ninguém
   entra sem um admin aprovar. Isso mantém o app publicável sem transformar
   o dono em cadastrador manual de e-mails.
