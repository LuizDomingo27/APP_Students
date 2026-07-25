# Arquitetura

## Visão geral

O projeto é dividido em dois pacotes com uma regra rígida entre eles:

- **`acervo/`** — o domínio: modelos, parsers, persistência e serviços.
  Não importa Streamlit em lugar nenhum. Tudo aqui é testável sem UI.
- **`app/`** — a interface Streamlit: só apresentação. Toda lógica de dados
  chega através dos serviços de `acervo/search/`.

Os scripts de `scripts/` são CLIs finos: parseiam argumentos, chamam um
serviço e imprimem o resultado.

```
UI (app/paginas/*)         CLI (scripts/*)
        │                        │
        └──────────┬─────────────┘
                   ▼
        serviços (acervo/search/*)      ← validação, orquestração, fronteira de erro
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
  - `UploadError` — idem para a página Adicionar.

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

## Interface (`app/`)

- `streamlit_app.py`: `set_page_config` + tema + navbar própria
  (`st.segmented_control`) que roteia para `busca`, `dashboard` ou
  `adicionar`. Captura `ConfiguracaoError`/`AcervoError` e mostra erro
  amigável.
- `tema.py`: paleta exportada (constantes usadas também nos gráficos Altair)
  e CSS injetado uma vez. **Atenção**: o override global de fonte exclui os
  ícones do Streamlit (`stIconMaterial` precisa da fonte Material Symbols —
  sem a exceção, ícones viram texto tipo "arrow_right").
- `componentes.py`: helpers **puros** (resumir, formatar_numero,
  total_de_paginas, rotulo_categoria, previa_de_codigo) — são esses que os
  testes unitários cobrem — e componentes com `st.*` (card de resultado,
  paginação por callbacks em `session_state`).
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
