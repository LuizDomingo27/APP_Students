import json
import uuid
from pathlib import Path

import pytest

from acervo.core.exceptions import ArquivoParseError
from acervo.ingestion.parsers import notebook_parser


def _escrever_notebook(caminho: Path, cells: list[dict]) -> None:
    cells_completas = []
    for cell in cells:
        completa = {"metadata": {}, "id": uuid.uuid4().hex[:8], **cell}
        if completa["cell_type"] == "code":
            completa.setdefault("execution_count", None)
            completa.setdefault("outputs", [])
        cells_completas.append(completa)

    nb = {"cells": cells_completas, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    caminho.write_text(json.dumps(nb), encoding="utf-8")


def test_associa_markdown_anterior_ao_codigo_seguinte(tmp_path):
    caminho = tmp_path / "exemplo.ipynb"
    _escrever_notebook(caminho, [
        {"cell_type": "markdown", "source": ["Calcula a média de idade"]},
        {"cell_type": "code", "source": ["df['idade'].mean()"]},
    ])

    blocos = notebook_parser.parse(caminho)

    assert len(blocos) == 1
    assert blocos[0].explicacao == "Calcula a média de idade"
    assert blocos[0].codigo == "df['idade'].mean()"
    assert blocos[0].linguagem == "python"


def test_ignora_celulas_vazias(tmp_path):
    caminho = tmp_path / "vazio.ipynb"
    _escrever_notebook(caminho, [
        {"cell_type": "code", "source": ["   "]},
        {"cell_type": "code", "source": ["print(1)"]},
    ])

    blocos = notebook_parser.parse(caminho)

    assert len(blocos) == 1
    assert blocos[0].codigo == "print(1)"


def test_detecta_celula_sql_do_databricks(tmp_path):
    caminho = tmp_path / "databricks.ipynb"
    _escrever_notebook(caminho, [
        {"cell_type": "code", "source": ["%%sql\nSELECT * FROM carros"]},
    ])

    blocos = notebook_parser.parse(caminho)

    assert blocos[0].linguagem == "sql"


def test_notebook_corrompido_gera_erro_tratado(tmp_path):
    caminho = tmp_path / "corrompido.ipynb"
    caminho.write_text("{ isso nao e um json valido ][", encoding="utf-8")

    with pytest.raises(ArquivoParseError) as exc_info:
        notebook_parser.parse(caminho)

    assert "corrompido.ipynb" in str(exc_info.value)
