# Banco de dados

PostgreSQL serverless (Neon). Conexão via `DATABASE_URL` no `.env`
(veja `.env.example`). Todas as tabelas vivem no schema `acervo`
(configurável via `DB_SCHEMA`; os testes de integração criam schemas
descartáveis `acervo_test_*` com as mesmas migrações).

## Migrações

Arquivos SQL em `acervo/persistence/migrations/`, aplicados em ordem
alfabética por `scripts/aplicar_migrations.py`. O placeholder `{schema}` é
substituído pelo runner. O controle fica na tabela `schema_migrations`
(nome + data) — rodar de novo só aplica o que falta. **Tudo roda numa única
transação**: ou aplica o conjunto pendente inteiro, ou nada.

| Migração                   | O que faz                                                              |
|----------------------------|------------------------------------------------------------------------|
| `0001_init.sql`            | Tabelas, índices e extensão `pg_trgm`.                                |
| `0002_busca_sem_acento.sql`| Extensão `unaccent` + text search config `portugues_unaccent`; recria `blocos.texto_busca` com ela. |
| `0003_origem_arquivo.sql`  | Coluna `arquivos.origem` ('varredura' \| 'upload') — base da limpeza de órfãos. |

Para criar uma migração nova: adicione `0004_descricao.sql` usando
`"{schema}"` em todo identificador, e rode `python scripts/aplicar_migrations.py`.
Nunca edite uma migração já aplicada — crie a próxima.

## Tabelas

### `categorias`

Uma linha por categoria visível na UI (nome, subcategoria, cor do chip).

| Coluna       | Tipo   | Notas                                                            |
|--------------|--------|------------------------------------------------------------------|
| id           | SERIAL PK |                                                              |
| nome         | TEXT   | ex.: "Databricks"                                               |
| subcategoria | TEXT?  | ex.: "Módulo 1" (permite dois módulos do mesmo tema)            |
| cor          | TEXT   | hex usado nos chips e no gráfico do dashboard                    |
| pasta_raiz   | TEXT **UNIQUE** | chave natural do upsert. Pasta real do disco (indexação em lote) ou slug sintético `upload_<nome>` (categoria criada pela UI). |

- Categorias de varredura vêm de `config/categorias.json` (upsert a cada
  `indexar.py`). Categorias criadas na página Adicionar só existem no banco.

### `arquivos`

Um arquivo lógico do acervo.

| Coluna        | Tipo    | Notas                                                          |
|---------------|---------|----------------------------------------------------------------|
| id            | SERIAL PK |                                                             |
| caminho       | TEXT **UNIQUE** | chave natural do upsert. Varredura: caminho relativo com `/` (ex.: `Scripts_SQL/aula/01.sql`). Upload: `uploads/<pasta_raiz>/<nome>`. |
| categoria_id  | INT FK → categorias |                                                  |
| extensao      | TEXT    | com ponto, minúscula (`.ipynb`)                               |
| tipo          | TEXT    | CHECK: 'conteudo' \| 'dado' \| 'outro' (hoje só 'conteudo' é gravado) |
| tamanho_bytes | BIGINT  |                                                                |
| hash          | TEXT    | SHA-256 do conteúdo — é o que torna a indexação incremental e detecta duplicatas de upload. Indexado (`idx_arquivos_hash`). |
| duplicado_de  | INT? FK → arquivos | reservado (não usado atualmente)                   |
| origem        | TEXT    | CHECK: 'varredura' \| 'upload'. DEFAULT 'varredura'. **Uploads nunca são tocados pela limpeza de órfãos.** |
| atualizado_em | TIMESTAMPTZ | atualizado a cada upsert                                  |

### `blocos`

A unidade pesquisável — um trecho de conteúdo de um arquivo (célula de
notebook, bloco SQL, página de PDF, slide).

| Coluna      | Tipo      | Notas                                                        |
|-------------|-----------|--------------------------------------------------------------|
| id          | BIGSERIAL PK |                                                          |
| arquivo_id  | INT FK → arquivos **ON DELETE CASCADE** | apagar o arquivo leva os blocos junto — é isso que a limpeza de órfãos usa. |
| ordem       | INT       | posição no arquivo; UNIQUE (arquivo_id, ordem)               |
| titulo      | TEXT?     | ex.: "Página 3", "Slide 7"                                  |
| explicacao  | TEXT?     | texto em prosa (markdown, comentários, texto do PDF/slide)  |
| codigo      | TEXT?     | código executável                                            |
| linguagem   | TEXT?     | 'python' \| 'sql' \| 'javascript' \| NULL                  |
| texto_busca | tsvector **GERADO** | `to_tsvector('acervo.portugues_unaccent', titulo ‖ explicacao ‖ codigo)` — recalculado pelo Postgres a cada insert/update, nada a manter no código. |
| criado_em   | TIMESTAMPTZ |                                                            |

Campos de texto passam por `_sanitizar_texto` antes do insert: remove bytes
NUL (o Postgres rejeita `\x00` em TEXT) e trunca em 50.000 caracteres
(o tsvector gerado tem limite duro de ~1 MB somando os três campos).

### `falhas_indexacao`

Log de arquivos que não puderam ser processados (append-only; o dashboard
mostra o total).

| Coluna          | Notas                                                  |
|-----------------|--------------------------------------------------------|
| arquivo_caminho | caminho relativo do arquivo que falhou                 |
| etapa           | quem falhou: nome do parser, 'infraestrutura', 'desconhecida' |
| erro            | mensagem da causa                                      |
| ocorrido_em     | timestamp                                              |

## Índices e mecânica da busca

| Índice                   | Tipo | Serve a                                              |
|--------------------------|------|------------------------------------------------------|
| `idx_blocos_tsv`         | GIN sobre `texto_busca` | busca full-text (modo **Texto**)  |
| `idx_blocos_codigo_trgm` | GIN `gin_trgm_ops` sobre `codigo` | busca literal (modo **Código**) |
| `idx_arquivos_hash`      | BTREE | checagem incremental / duplicatas                   |
| `idx_arquivos_categoria` | BTREE | joins e filtros por categoria                       |

**Modo Texto** (`BuscaRepository.buscar_texto`): usa
`websearch_to_tsquery('acervo.portugues_unaccent', termo)` — sintaxe de busca
web (aspas, OR, -exclusão) que nunca levanta erro de sintaxe para input do
usuário — casada contra `texto_busca` e ranqueada por `ts_rank`. A
configuração `portugues_unaccent` (migração 0002) aplica `unaccent` +
stemming português **nos dois lados**, então "regressao" encontra
"regressão" e "consultas" encontra "consulta".

**Modo Código** (`buscar_codigo`): `codigo ILIKE %termo%` com curingas
escapados (buscar "100%" funciona literal), coberto pelo índice trigram, e
ordenado por `similarity(codigo, termo)`. É o caminho certo para termos que
o stemmer destruiria: `df.groupby`, `LEFT JOIN`, `pg_settings`.

Ambos devolvem o total geral via janela `count(*) OVER ()` — uma única query
traz a página e o total para a paginação.

## Consultas úteis de manutenção

```sql
-- visão geral
SELECT origem, count(*) FROM acervo.arquivos GROUP BY origem;

-- últimas falhas de indexação
SELECT arquivo_caminho, etapa, left(erro, 80), ocorrido_em
FROM acervo.falhas_indexacao ORDER BY ocorrido_em DESC LIMIT 10;

-- arquivos de uma categoria
SELECT a.caminho, a.extensao, a.atualizado_em
FROM acervo.arquivos a JOIN acervo.categorias c ON c.id = a.categoria_id
WHERE c.nome = 'Scripts SQL' ORDER BY a.caminho;

-- remover um upload específico (blocos caem em cascata)
DELETE FROM acervo.arquivos WHERE caminho = 'uploads/<pasta>/<arquivo>';
```
