"""Camada de acesso a conexão com o banco (Neon/Postgres).

Regras de robustez desta camada:
  - Um único pool de conexões reaproveitado pelo processo inteiro.
  - Obter uma conexão do pool tem retry com backoff (o Neon serverless pode
    ter "cold start" ou derrubar conexões ociosas) — falhas de rede
    transitórias não devem propagar na primeira tentativa.
  - Qualquer erro de baixo nível do driver (psycopg.Error) é convertido em
    `ConexaoBancoError`, para que as camadas acima nunca precisem conhecer
    psycopg diretamente.
  - `cursor()` garante commit em caso de sucesso e rollback em caso de erro,
    e sempre devolve a conexão ao pool (`finally`), mesmo em falha.
"""
import logging
import time
from contextlib import contextmanager
from typing import Optional

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from acervo.core.exceptions import ConexaoBancoError
from acervo.settings import get_settings

logger = logging.getLogger("acervo.db")

_MAX_TENTATIVAS_CONEXAO = 3
_ESPERA_BASE_SEGUNDOS = 0.5

_pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=5,
            timeout=10,
            open=True,
        )
    return _pool


def fechar_pool() -> None:
    """Fecha o pool (usado em testes e no encerramento do app)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _obter_conexao() -> psycopg.Connection:
    """Obtém uma conexão do pool, com retry para falhas transitórias.

    Só cobre a etapa de OBTER a conexão — uma vez que o código do chamador
    já está executando comandos, não tentamos de novo automaticamente,
    porque a operação pode já ter tido efeito parcial.
    """
    pool = get_pool()
    ultimo_erro: Optional[Exception] = None
    for tentativa in range(1, _MAX_TENTATIVAS_CONEXAO + 1):
        try:
            return pool.getconn(timeout=10)
        except (psycopg.OperationalError, PoolTimeout) as e:
            ultimo_erro = e
            logger.warning(
                "Falha ao obter conexão com o Neon (tentativa %s/%s): %s",
                tentativa, _MAX_TENTATIVAS_CONEXAO, e,
            )
            if tentativa < _MAX_TENTATIVAS_CONEXAO:
                time.sleep(_ESPERA_BASE_SEGUNDOS * tentativa)

    raise ConexaoBancoError(
        f"Não foi possível conectar ao banco Neon após {_MAX_TENTATIVAS_CONEXAO} "
        f"tentativas: {ultimo_erro}"
    ) from ultimo_erro


@contextmanager
def cursor():
    """Fornece um cursor com commit/rollback automático.

    Uso:
        with cursor() as cur:
            cur.execute(...)
    """
    pool = get_pool()
    conn = _obter_conexao()
    try:
        with conn.cursor() as cur:
            try:
                yield cur
                conn.commit()
            except psycopg.Error as e:
                conn.rollback()
                raise ConexaoBancoError(f"Erro ao executar operação no banco: {e}") from e
            except Exception:
                conn.rollback()
                raise
    finally:
        pool.putconn(conn)
