"""Serviço de busca (Fase 2) — a porta de entrada que a UI e o CLI usam.

Responsabilidades desta camada (e só dela):
  - validar o input do usuário (termo vazio, modo inexistente, paginação
    absurda) e falhar cedo com `BuscaError`, antes de tocar o banco;
  - traduzir "página" (conceito da UI) em limite/offset (conceito do SQL);
  - escolher a variante certa do repositório conforme o modo;
  - converter qualquer falha de infraestrutura em `BuscaError`, para que a
    UI só precise conhecer uma exceção.

Modos de busca:
  - "texto"  → full-text em português com stemming e ranking (padrão).
  - "codigo" → trecho literal de código (ex.: "df.groupby", "LEFT JOIN").
"""
from typing import Optional

from acervo.core.exceptions import AcervoError, BuscaError
from acervo.core.models import Bloco, PaginaBusca
from acervo.persistence.db import cursor
from acervo.persistence.repository import BuscaRepository

MODOS_VALIDOS = ("texto", "codigo")
LIMITE_PADRAO = 20
LIMITE_MAXIMO = 100


def buscar(
    termo: str,
    *,
    modo: str = "texto",
    categoria_id: Optional[int] = None,
    linguagem: Optional[str] = None,
    pagina: int = 1,
    limite: int = LIMITE_PADRAO,
    schema: str = "acervo",
    repo: Optional[BuscaRepository] = None,
) -> PaginaBusca:
    termo = (termo or "").strip()
    if not termo:
        raise BuscaError("Informe um termo de busca.")
    if modo not in MODOS_VALIDOS:
        raise BuscaError(f"Modo de busca inválido: '{modo}'. Use um de: {', '.join(MODOS_VALIDOS)}.")
    if pagina < 1:
        raise BuscaError("A página deve ser 1 ou maior.")
    if not 1 <= limite <= LIMITE_MAXIMO:
        raise BuscaError(f"O limite deve estar entre 1 e {LIMITE_MAXIMO}.")

    repo = repo or BuscaRepository(schema)
    offset = (pagina - 1) * limite
    buscar_fn = repo.buscar_texto if modo == "texto" else repo.buscar_codigo

    try:
        with cursor() as cur:
            resultados, total = buscar_fn(
                cur, termo,
                categoria_id=categoria_id, linguagem=linguagem,
                limite=limite, offset=offset,
            )
    except BuscaError:
        raise
    except AcervoError as e:
        raise BuscaError(f"A busca falhou: {e}") from e

    return PaginaBusca(
        resultados=tuple(resultados),
        total=total,
        pagina=pagina,
        limite=limite,
    )


def conteudo_do_arquivo(
    arquivo_caminho: str,
    *,
    schema: str = "acervo",
    repo: Optional[BuscaRepository] = None,
) -> list[Bloco]:
    """Todos os blocos de um arquivo, na ordem original — para a tela de detalhe."""
    arquivo_caminho = (arquivo_caminho or "").strip()
    if not arquivo_caminho:
        raise BuscaError("Informe o caminho do arquivo.")

    repo = repo or BuscaRepository(schema)
    try:
        with cursor() as cur:
            return repo.blocos_do_arquivo(cur, arquivo_caminho)
    except AcervoError as e:
        raise BuscaError(f"Não foi possível carregar o arquivo '{arquivo_caminho}': {e}") from e


def opcoes_de_filtro(
    *,
    schema: str = "acervo",
    repo: Optional[BuscaRepository] = None,
) -> dict:
    """Categorias e linguagens existentes — popula os filtros da UI."""
    repo = repo or BuscaRepository(schema)
    try:
        with cursor() as cur:
            return {
                "categorias": repo.listar_categorias(cur),
                "linguagens": repo.listar_linguagens(cur),
            }
    except AcervoError as e:
        raise BuscaError(f"Não foi possível carregar os filtros: {e}") from e
