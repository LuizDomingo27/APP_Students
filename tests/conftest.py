"""Fixtures compartilhadas.

`schema_teste` só é usada pelos testes de integração (marcados com
`@pytest.mark.integration`): sem DATABASE_URL configurado, eles são pulados
automaticamente em vez de falhar — assim o dev sem acesso ao Neon ainda
roda a suíte inteira de testes unitários normalmente.
"""
import os
import uuid

import psycopg
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requer DATABASE_URL configurado (banco Neon real)")


@pytest.fixture(scope="session")
def schema_teste():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL não configurado — pulando testes de integração com o Neon")

    from acervo.settings import get_settings
    from scripts.aplicar_migrations import aplicar

    nome_schema = f"acervo_test_{uuid.uuid4().hex[:8]}"
    aplicar(schema=nome_schema)

    yield nome_schema

    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{nome_schema}" CASCADE')
        conn.commit()
