"""Aplica as migrações de schema (acervo/persistence/migrations/*.sql) no
banco configurado em DATABASE_URL.

Uso:
    python scripts/aplicar_migrations.py                # aplica no schema "acervo"
    python scripts/aplicar_migrations.py --schema outro # aplica em outro schema (ex.: testes)

Idempotente: mantém um registro em "{schema}".schema_migrations e só aplica
o que ainda não rodou.
"""
import argparse
import logging
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import psycopg

from acervo.core.exceptions import ConexaoBancoError
from acervo.settings import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "acervo" / "persistence" / "migrations"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("acervo.migrations")


def aplicar(schema: str = "acervo") -> None:
    settings = get_settings()
    arquivos = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not arquivos:
        logger.warning("Nenhum arquivo de migração encontrado em %s", MIGRATIONS_DIR)
        return

    try:
        with psycopg.connect(settings.database_url, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute(
                    f'CREATE TABLE IF NOT EXISTS "{schema}".schema_migrations '
                    f'(nome TEXT PRIMARY KEY, aplicada_em TIMESTAMPTZ NOT NULL DEFAULT now())'
                )
                cur.execute(f'SELECT nome FROM "{schema}".schema_migrations')
                aplicadas = {row[0] for row in cur.fetchall()}

                for caminho in arquivos:
                    if caminho.name in aplicadas:
                        logger.info("Já aplicada: %s", caminho.name)
                        continue
                    sql = caminho.read_text(encoding="utf-8").format(schema=schema)
                    logger.info("Aplicando migração: %s (schema=%s)", caminho.name, schema)
                    cur.execute(sql)
                    cur.execute(
                        f'INSERT INTO "{schema}".schema_migrations (nome) VALUES (%s)',
                        (caminho.name,),
                    )
            conn.commit()
    except psycopg.Error as e:
        raise ConexaoBancoError(f"Falha ao aplicar migrações no schema '{schema}': {e}") from e

    logger.info("Migrações aplicadas com sucesso no schema '%s'.", schema)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="Aplica migrações de schema no banco Neon.")
    argparser.add_argument("--schema", default="acervo")
    args = argparser.parse_args()
    aplicar(schema=args.schema)
