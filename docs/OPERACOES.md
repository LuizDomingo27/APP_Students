# Operações e manutenção

Receitas para as tarefas do dia a dia e para evoluir o app com segurança.

## Contexto importante: o fluxo atual do acervo

As 8 pastas de curso originais (`SQL_SERVER`, `POSTGREES`, `Estatistica_DS`,
`DataBriks2`, `Databriks_Udemy`, `Engenharia_PY`, `Scripts_SQL`,
`DataScience_UD`) **já foram indexadas e removidas do disco** (movidas para a
Lixeira em 25/07/2026). O conteúdo delas vive só no banco — 505 arquivos,
6.595 blocos. Por isso:

- A limpeza de órfãos **preserva** registros de pastas raiz que não existem
  mais no disco (é o comportamento esperado, não um bug).
- Os ~267 arquivos de tipos não indexáveis dessas pastas (datasets .csv/.xlsx,
  .zip, instaladores) **não estão no banco** — só na Lixeira, até ela ser
  esvaziada.
- Conteúdo novo entra pela página **Adicionar** do app.

## Acesso ao acervo

O app não é mais aberto: só entra quem tem cadastro **aprovado**. Cadastrar-se
é auto-serviço (aba "Criar conta" na tela de entrada), mas a conta nasce
`pendente` e não vê nada até um admin aprovar.

### Criar o primeiro administrador

O primeiro admin não tem quem o aprove — ele é criado pelo servidor, por quem
tem acesso ao `.env`:

```bash
python scripts/criar_admin.py --email voce@exemplo.com --nome "Seu Nome"
```

A senha é pedida no terminal, nunca na linha de comando (argumento vai para o
histórico do shell, para a lista de processos e para logs de auditoria). O
script é **idempotente**: se a conta já existir, ela é promovida (papel
`admin`, status `aprovado`) em vez de falhar, e a senha só é tocada com
`--redefinir-senha`. Use `--schema` para agir em outro schema.

### Aprovar, bloquear, resetar senha

Tudo pelo painel **Usuários** (visível só para admins):

| Situação | O que fazer |
|----------|-------------|
| Cadastro novo esperando | Aba **Pendentes** → **Aprovar** (ou **Recusar**). |
| Tirar o acesso de alguém | Aba **Ativos** → **Bloquear**. O cadastro permanece; dá para reativar depois. |
| Pessoa perdeu a senha | Aba **Ativos** → **Resetar senha**. A senha temporária aparece **uma vez** — anote e entregue em mãos. Quem entrar com ela é obrigado a definir uma senha própria antes de ver qualquer página. |
| Promover outro admin | Aba **Ativos** → **Tornar admin**. |
| Devolver acesso | Aba **Recusados e bloqueados** → **Reativar** / **Aprovar mesmo assim**. |

O que o painel **não** deixa fazer, por desenho: agir sobre a própria conta
(bloquear-se, rebaixar-se, resetar a própria senha — para essa use o menu da
conta na navbar) e remover o último administrador ativo. Nada é apagado:
recusar e bloquear são status, e o registro fica com quem decidiu e quando.

### Trocar a própria senha

Menu da conta na navbar (o botão com seu nome, à direita) → **Trocar senha**.
O mesmo menu tem o **Sair**. Recarregar a página (F5) também encerra a
sessão: ela vive só em memória, de propósito.

## Adicionar conteúdo novo

### Pela interface (caminho normal)

App → aba **Adicionar** → escolha a categoria (ou crie uma nova) → envie os
arquivos → "Adicionar ao acervo". Formatos: `.ipynb`, `.sql`, `.py`, `.md`,
`.txt`, `.js`, `.pdf`, `.pptx`. O conteúdo é extraído na hora e gravado com
`origem='upload'`; o arquivo em si não precisa ficar em lugar nenhum.

Resultados possíveis por arquivo:
- **adicionado / atualizado** — gravado (atualizado = mesmo nome, conteúdo novo);
- **sem alterações** — arquivo idêntico já estava no acervo;
- **duplicado** — conteúdo byte a byte idêntico existe com outro nome (mostra
  qual); não regrava;
- **erro** — arquivo ilegível/corrompido; os demais do lote seguem normalmente.

### Em lote, por pastas no disco

Para indexar uma pasta inteira de uma vez:

1. Coloque a pasta na raiz do projeto (ex.: `NovoCurso/`).
2. Registre-a em `config/categorias.json`:
   ```json
   "NovoCurso": { "categoria": "Novo Curso", "subcategoria": null, "cor": "#f59e0b" }
   ```
3. Rode:
   ```bash
   python scripts/indexar.py
   ```
   Saída: `ResultadoIndexacao(processados=N, pulados_sem_alteracao=N, ignorados_tipo=N, falhas=N)`.
   É incremental (hash SHA-256): rodar de novo só processa o que mudou.
4. Confira falhas (se houver) na tabela `falhas_indexacao`.
5. Quando quiser, remova a pasta do disco — os registros ficam no banco.

## Limpeza de órfãos

Remove do banco registros de arquivos que sumiram do disco. Use após
renomear/reorganizar arquivos **dentro** de uma pasta ainda presente.

```bash
python scripts/limpar_orfaos.py             # simulação: lista, não remove
python scripts/limpar_orfaos.py --aplicar   # remove de fato
```

Salvaguardas (por desenho — ver `acervo/search/limpeza_service.py`):
- Pasta raiz inteira ausente → **tudo preservado** (conteúdo arquivado no banco).
- `origem='upload'` → **nunca** entra na reconciliação.
- Sem `--aplicar`, nada é removido, nunca.

## Manutenções comuns no código

### Suportar um novo formato de arquivo (ex.: `.docx`)

1. Crie `acervo/ingestion/parsers/docx_parser.py` seguindo o contrato de
   `base.py`: `parse(caminho: Path) -> list[BlocoBruto]`, levantando
   `ArquivoParseError(caminho, "docx_parser", causa)` quando não abrir.
2. Registre a extensão em `scanner.EXTENSOES_PARSERS`
   (`".docx": "docx"`) — o upload da UI passa a aceitá-la automaticamente
   (a lista vem de `upload_service.extensoes_aceitas()`).
3. Registre o parser em `indexador_service._PARSERS` (`"docx": docx_parser.parse`).
4. Adicione a dependência em `requirements.txt` e escreva
   `tests/unit/test_docx_parser.py` (modelo: `test_pdf_parser.py`).

### Nova página na interface

1. Crie `app/paginas/minha_pagina.py` com uma função `render()`.
2. Em `app/streamlit_app.py`: importe e adicione o ramo no roteamento
   (`_pagina`). O rótulo entra em `componentes.PAGINAS_ABERTAS` — ou, se a
   página for só para admins, em `componentes.opcoes_de_navegacao`, junto com
   `PAGINA_ADMIN`.
3. Dados sempre via serviços de `acervo/search/`; consultas repetidas com
   `@st.cache_data(ttl=...)`.
4. Se a página fizer algo restrito, **a checagem de permissão vai no serviço**,
   não na página: esconder o botão é conveniência visual (ver
   `acervo/auth/admin_service.py`).

### Mudança de schema do banco

Crie `acervo/persistence/migrations/0005_*.sql` (nunca edite as aplicadas),
usando `"{schema}"` nos identificadores, e rode
`python scripts/aplicar_migrations.py`. Atualize o dataclass em
`core/models.py` e os métodos do repositório em conjunto.

### Cuidados com o tema (`app/tema.py`)

O CSS aplica a fonte Inter globalmente. **Não remova a exceção
`[data-testid="stIconMaterial"]`** — sem ela os ícones do Streamlit
(expander, uploader) viram texto literal ("arrow_right"). Cores novas: sempre
como constante exportada em `tema.py` (os gráficos do dashboard importam de lá).

## Testes

```bash
python -m pytest tests/unit -q     # < 5 s, sem banco (fakes em memória)
python -m pytest tests -q          # + integração: exige DATABASE_URL no .env
python -m ruff check acervo app scripts tests
```

- **Unitários**: serviços testados com repositórios falsos injetados
  (padrão em `test_indexador_service.py`, `test_limpeza_service.py`,
  `test_upload_service.py`; para autenticação, o `FakeUsuarioRepo` de
  `tests/unit/fakes.py` em `test_auth_service.py` e `test_admin_service.py`);
  parsers testados com arquivos em `tmp_path`; regras de senha em
  `test_senhas.py`; helpers puros da UI em `test_ui_componentes.py`,
  `test_ui_usuarios.py` e `test_sessao.py` (o `session_state` do Streamlit
  funciona em "bare mode", sem servidor).
- **Integração** (marker `integration`): criam um schema descartável
  `acervo_test_<hex>` no Neon real, aplicam as migrações nele e o derrubam no
  fim — nunca tocam o schema `acervo` de produção.

Avisos pré-existentes do ruff (E741 no sql_parser, E402 nos scripts — o
`sys.path.insert` precisa vir antes dos imports, F841 num teste) são
conhecidos e inofensivos.

## Rodando o app

```bash
streamlit run app/streamlit_app.py
```

No Claude Code, o dev server está configurado em `.claude/launch.json`
(nome `acervo-ui`, porta 8501). O tema base fica em `.streamlit/config.toml`;
o refinamento visual em `app/tema.py`.

A primeira tela é sempre o login — se ainda não existe nenhum administrador,
crie um com `scripts/criar_admin.py` (acima) antes de subir o app.

## Troubleshooting

| Sintoma | Causa provável | O que fazer |
|---------|----------------|-------------|
| "DATABASE_URL não definido" | `.env` ausente/incompleto | `copy .env.example .env` e preencher com a connection string do Neon. |
| "Não foi possível conectar ao banco Neon após 3 tentativas" | Neon hibernado, rede, ou URL errada | Testar a URL no painel do Neon; o retry já cobre cold start normal. |
| Conteúdo novo não aparece na busca | Cache da UI (TTL 5–10 min) | Tecla `C` → Clear cache no app, ou aguardar o TTL. O upload pela página Adicionar já limpa o cache sozinho. |
| Upload recusado: "Extensão não suportada" | Formato sem parser | Ver receita "novo formato" acima. |
| Upload avisa "duplicado" | Conteúdo idêntico já existe (hash igual) | Comportamento correto — evita duplicar o acervo. A mensagem diz qual arquivo já tem aquele conteúdo. |
| Falhas > 0 na indexação | Arquivo corrompido/ilegível | `SELECT * FROM acervo.falhas_indexacao ORDER BY ocorrido_em DESC` — a `etapa` diz qual parser falhou. (Falha histórica conhecida: um `.pptx` de 0 bytes.) |
| Ícones da UI viram texto ("arrow_right") | Exceção de fonte removida do tema | Restaurar a regra `stIconMaterial` em `app/tema.py`. |
| Acentos quebrados no terminal Windows | Console cp1252 | Os scripts CLI já forçam UTF-8 (`scripts/buscar.py`); em comandos `python -c`, evite acentos ou use `PYTHONIOENCODING=utf-8`. |
| Erro "bytes NUL" ou tsvector muito grande | Texto não sanitizado chegou ao banco | Garanta que inserts de blocos passem por `_sanitizar_texto` (indexador e upload já passam). |
| Só aparece a tela de login, ninguém entra | Nenhum admin criado ainda, ou todos pendentes | `python scripts/criar_admin.py --email … --nome …` e aprove os demais pelo painel. |
| "Seu cadastro foi recebido e aguarda aprovação" | Conta pendente | Um admin precisa aprovar na aba **Pendentes**. |
| "E-mail ou senha incorretos" com senha certa | A mensagem é a mesma para e-mail inexistente e senha errada (de propósito: a tela é pública) | Confira o e-mail; se persistir, um admin reseta a senha pelo painel. |
| "Muitas tentativas seguidas. Tente de novo em Ns" | Freio de 5 falhas por sessão | Esperar os 60 s (ou recarregar a página, já que a sessão vive só em memória). |
| Deslogou sozinho ao recarregar | Comportamento esperado | A sessão vive só no `session_state`, que o Streamlit descarta a cada conexão nova — decisão registrada em `app/sessao.py`. |
| "Não é possível bloquear o último administrador ativo" | Salvaguarda do `admin_service` | Promova outro admin antes (aba **Ativos** → **Tornar admin**). |
| Perdeu a senha temporária que o painel mostrou | Ela aparece uma vez só, e o banco só tem o hash | Gerar outra em **Resetar senha**. |
