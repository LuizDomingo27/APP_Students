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
| `0004_usuarios.sql`        | Tabela `usuarios` + índice por status — o acervo deixa de ser aberto. |

Para criar uma migração nova: adicione `0005_descricao.sql` usando
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

### `usuarios`

Quem pode entrar no acervo. Cadastro é auto-serviço, mas nasce `pendente` e
não abre porta nenhuma até um admin decidir.

| Coluna           | Tipo      | Notas                                                     |
|------------------|-----------|-----------------------------------------------------------|
| id               | SERIAL PK |                                                           |
| nome             | TEXT      | como a pessoa se identificou no cadastro                  |
| email            | TEXT **UNIQUE** | sempre gravado em minúsculas pela camada de serviço — o UNIQUE do Postgres é sensível a maiúsculas, então sem a normalização "Ana@x.com" e "ana@x.com" virariam duas contas. |
| senha_hash       | TEXT      | Argon2id. **Nunca sai do par repositório↔`acervo.auth`**: o dataclass `Usuario` não tem esse campo, então nenhum objeto que chega à UI, a um log ou ao `session_state` carrega credencial. |
| papel            | TEXT      | CHECK: 'usuario' \| 'admin'. DEFAULT 'usuario'            |
| status           | TEXT      | CHECK: 'pendente' \| 'aprovado' \| 'recusado' \| 'bloqueado'. DEFAULT 'pendente'. Só 'aprovado' entra no app. |
| senha_temporaria | BOOLEAN   | ligado quando um admin reseta a senha; enquanto for TRUE a interface só mostra a tela de troca de senha. |
| criado_em        | TIMESTAMPTZ | DEFAULT now()                                           |
| decidido_em      | TIMESTAMPTZ? | quando a última decisão administrativa aconteceu       |
| decidido_por     | INT? FK → usuarios | quem decidiu. Evita uma tabela de auditoria separada enquanto só interessa o estado corrente. |
| ultimo_acesso    | TIMESTAMPTZ? | gravado a cada login bem-sucedido                       |

Ciclo de vida do status:

```
pendente  -> aprovado | recusado      (decisão inicial do admin)
aprovado <-> bloqueado                (revogar / devolver acesso)
recusado  -> aprovado                 (admin muda de ideia)
```

**Nada é apagado.** Recusar e bloquear são status: manter a linha preserva o
histórico da decisão e impede que a mesma pessoa volte para a fila de
pendentes só recriando o cadastro com o mesmo e-mail. Não há `DELETE` de
usuário em lugar nenhum do código.

O índice `idx_usuarios_status` serve à consulta que o painel do admin faz a
cada carga (a fila de pendentes).

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

-- quem está esperando aprovação
SELECT nome, email, criado_em FROM acervo.usuarios
WHERE status = 'pendente' ORDER BY criado_em;

-- quem tem acesso hoje, e quem manda
SELECT nome, email, papel, ultimo_acesso FROM acervo.usuarios
WHERE status = 'aprovado' ORDER BY papel, nome;
```

> Para mexer em usuário, prefira o painel **Usuários** do app ou o
> `scripts/criar_admin.py`. SQL na mão pula as salvaguardas ("sempre resta um
> admin", transições de status válidas) e não grava `decidido_por`.
