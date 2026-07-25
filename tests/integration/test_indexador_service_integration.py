"""Roda o indexador de ponta a ponta contra um schema descartável no Neon,
sobre uma pasta de conteúdo fictícia (não toca os dados reais do acervo).
"""
import json

import pytest

from acervo.ingestion import scanner
from acervo.persistence.db import cursor
from acervo.persistence.repository import ArquivoRepository, FalhaRepository
from acervo.search.indexador_service import indexar_tudo

pytestmark = pytest.mark.integration


def test_indexacao_ponta_a_ponta_isola_arquivo_corrompido(tmp_path, monkeypatch, schema_teste):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    categorias = {"SQL_TESTE": {"categoria": "SQL Server", "subcategoria": None, "cor": "#a78bfa"}}
    (config_dir / "categorias.json").write_text(json.dumps(categorias), encoding="utf-8")
    monkeypatch.setattr(scanner, "CONFIG_CATEGORIAS", config_dir / "categorias.json")

    pasta = tmp_path / "SQL_TESTE"
    pasta.mkdir()
    (pasta / "bom.sql").write_text("-- lista tudo\nSELECT * FROM tabela;", encoding="utf-8")
    (pasta / "corrompido.ipynb").write_text("{ nao e json valido ][", encoding="utf-8")

    resultado = indexar_tudo(schema=schema_teste, raiz=tmp_path)

    assert resultado.processados == 1
    assert resultado.falhas == 1

    arquivos_repo = ArquivoRepository(schema_teste)
    falhas_repo = FalhaRepository(schema_teste)
    with cursor() as cur:
        assert arquivos_repo.hash_ja_indexado(
            cur, "SQL_TESTE/bom.sql", scanner.calcular_hash(pasta / "bom.sql"),
        )
        cur.execute(f'SELECT arquivo_caminho FROM "{schema_teste}".falhas_indexacao')
        falhas = [row[0] for row in cur.fetchall()]

    assert "SQL_TESTE/corrompido.ipynb" in falhas
