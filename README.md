# Acervo DS

Acervo pessoal de estudos de Data Science, pesquisável. Extrai o conteúdo de
notebooks Jupyter, scripts SQL/Python, PDFs e slides de cursos, grava tudo em
um banco PostgreSQL (Neon) e oferece uma interface web (Streamlit) com busca
full-text em português, busca literal de código, dashboard e upload de novos
conteúdos — atrás de login, com cadastro aprovado por um administrador.

> **O banco é a fonte da verdade.** As pastas de curso originais já foram
> indexadas e removidas do disco — todo o conteúdo vive no banco. Conteúdo
> novo entra pela página **Adicionar** do app (ou, para lotes grandes em
> pastas, pelo `scripts/indexar.py`).

## Stack

| Camada        | Tecnologia                                              |
|---------------|---------------------------------------------------------|
| Interface     | Streamlit (tema dark customizado, Altair para gráficos) |
| Banco         | PostgreSQL serverless (Neon) via psycopg 3 + pool       |
| Busca         | `tsvector` português sem acento + trigram (`pg_trgm`)   |
| Acesso        | Argon2id (argon2-cffi), sessão em memória do Streamlit  |
| Extração      | nbformat (.ipynb), pypdf (.pdf), python-pptx (.pptx)    |
| Testes        | pytest (unitários em memória + integração no Neon)      |

## Como rodar

```bash
# 1. dependências
pip install -r requirements.txt

# 2. configuração (uma vez): copie e preencha o DATABASE_URL do Neon
#    (painel do Neon -> Connection Details -> Connection string)
copy .env.example .env

# 3. schema do banco (idempotente — só aplica o que falta)
python scripts/aplicar_migrations.py

# 4. primeiro administrador (a senha é pedida no terminal)
python scripts/criar_admin.py --email voce@exemplo.com --nome "Seu Nome"

# 5. interface web
streamlit run app/streamlit_app.py
```

A interface abre em `http://localhost:8501` na tela de entrada. Quem não tem
conta pode criar uma ali mesmo, mas ela nasce **pendente**: só entra no acervo
depois que um administrador aprova, no painel **Usuários**. Aprovado, o app
tem quatro páginas (a última só para admins):

- **Busca** — full-text ("regressão linear") ou trecho literal de código
  ("df.groupby"), com filtros por categoria, conteúdo e linguagem, paginação e
  visualização do arquivo completo. O filtro de conteúdo depende da categoria:
  escolhida a categoria, ele lista os arquivos dela (capítulos, notebooks,
  slides) e, sem termo digitado, mostra o sumário do conteúdo escolhido.
- **Dashboard** — totais do acervo e distribuição de blocos por categoria.
- **Adicionar** — upload de novos conteúdos direto para o banco
  (`.ipynb`, `.sql`, `.py`, `.md`, `.txt`, `.js`, `.pdf`, `.pptx`), com criação
  de categorias e detecção de duplicatas.
- **Usuários** (admin) — fila de cadastros pendentes, aprovação/recusa,
  bloqueio e reativação, promoção a admin e reset de senha (a senha temporária
  aparece uma vez e obriga a pessoa a definir a sua no primeiro acesso).

## Scripts de linha de comando

| Script                          | O que faz                                                                 |
|---------------------------------|---------------------------------------------------------------------------|
| `scripts/aplicar_migrations.py` | Aplica as migrações SQL pendentes (`--schema` para schema alternativo).  |
| `scripts/criar_admin.py`        | Cria (ou promove) um administrador. Senha pedida no terminal; idempotente; `--redefinir-senha` para trocar a senha de uma conta existente. |
| `scripts/indexar.py`            | Varre as pastas de `config/categorias.json` e indexa (incremental).      |
| `scripts/limpar_orfaos.py`      | Remove registros de arquivos que sumiram do disco. **Dry-run por padrão**; `--aplicar` para valer. |
| `scripts/buscar.py`             | Busca no acervo pelo terminal (`--modo codigo`, `--categoria`, `--limite`). |
| `scripts/gerar_inventario.py`   | (Fase 0, histórico) Inventário de arquivos e detecção de duplicatas em `data/`. |

## Mapa do projeto

```
acervo/                  # pacote de domínio — NADA de Streamlit aqui
  settings.py            # lê .env, expõe get_settings() (DATABASE_URL etc.)
  core/
    models.py            # dataclasses: Categoria, Arquivo, Bloco, ResultadoBusca, Usuario…
    exceptions.py        # hierarquia AcervoError (Configuracao, ConexaoBanco, Parse, Busca, Upload, Cadastro, Autenticacao, Permissao)
  ingestion/
    scanner.py           # varre pastas configuradas, calcula hash, decide o parser
    parsers/             # um parser por formato -> list[BlocoBruto]
  persistence/
    db.py                # pool de conexões + cursor() com commit/rollback/retry
    repository.py        # única camada que conhece SQL
    migrations/          # 0001 schema, 0002 busca sem acento, 0003 coluna origem, 0004 usuários
  search/                # serviços (orquestração) — a porta de entrada de UI e CLI
    indexador_service.py # indexação em lote, tolerante a falhas por arquivo
    upload_service.py    # upload pela interface (origem='upload')
    limpeza_service.py   # limpeza de órfãos com salvaguardas
    busca_service.py     # validação de input + busca paginada
    estatisticas_service.py
  auth/                  # quem entra: cadastro, login e gestão de usuários
    senhas.py            # Argon2id, validação e senha temporária (funções puras)
    auth_service.py      # cadastrar / autenticar / alterar_senha
    admin_service.py     # aprovar, bloquear, papel, reset — permissão decidida aqui

app/                     # interface Streamlit — SÓ apresentação
  streamlit_app.py       # entrada: portão de acesso + navbar + roteamento
  sessao.py              # quem está logado nesta aba (session_state, só em memória)
  tema.py                # paleta e CSS injetado (única fonte de cores)
  componentes.py         # cards, chips, paginação (helpers puros são testados)
  paginas/               # busca.py, dashboard.py, adicionar.py,
                         # login.py, trocar_senha.py, usuarios.py

config/categorias.json   # pasta do disco -> categoria/cor (só p/ indexação em lote)
scripts/                 # CLIs finos (parse de argumentos + chamada de serviço)
tests/unit/              # sem banco: fakes em memória
tests/integration/       # exigem DATABASE_URL (criam schema descartável)
docs/                    # documentação detalhada (abaixo)
```

## Documentação detalhada

| Documento                                    | Conteúdo                                                        |
|----------------------------------------------|-----------------------------------------------------------------|
| [docs/ARQUITETURA.md](docs/ARQUITETURA.md)   | Camadas, fluxos de dados, contratos entre módulos, decisões de projeto. |
| [docs/BANCO_DE_DADOS.md](docs/BANCO_DE_DADOS.md) | Schema completo, índices, mecânica da busca, migrações.     |
| [docs/OPERACOES.md](docs/OPERACOES.md)       | Receitas de manutenção: adicionar conteúdo/parser/categoria, limpeza, testes, troubleshooting. |

## Testes

```bash
python -m pytest tests/unit -q          # rápidos, sem banco
python -m pytest tests -q               # inclui integração (precisa de DATABASE_URL)
python -m ruff check acervo app scripts tests
```
