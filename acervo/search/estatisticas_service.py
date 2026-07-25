"""Números agregados do acervo — o serviço que o dashboard (Fase 3) consome."""
from typing import Optional

from acervo.core.exceptions import AcervoError, BuscaError
from acervo.core.models import ResumoAcervo
from acervo.persistence.db import cursor
from acervo.persistence.repository import EstatisticaRepository


def resumo_do_acervo(
    *,
    schema: str = "acervo",
    repo: Optional[EstatisticaRepository] = None,
) -> ResumoAcervo:
    repo = repo or EstatisticaRepository(schema)
    try:
        with cursor() as cur:
            return repo.resumo(cur)
    except AcervoError as e:
        raise BuscaError(f"Não foi possível carregar as estatísticas do acervo: {e}") from e
