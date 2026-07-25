"""Extrai blocos de código de notebooks Jupyter (.ipynb).

Cada célula de código vira um bloco; a célula markdown imediatamente
anterior (se houver) vira a "explicação" daquele bloco — é assim que os
notebooks de aula geralmente organizam texto + código.
"""
import json
from pathlib import Path

import nbformat

from acervo.core.exceptions import ArquivoParseError
from acervo.ingestion.parsers.base import BlocoBruto


def _detectar_linguagem(codigo: str) -> str:
    primeira_linha = codigo.strip().splitlines()[0] if codigo.strip() else ""
    if primeira_linha.startswith(("%%sql", "%sql")):
        return "sql"
    return "python"


def parse(caminho: Path) -> list[BlocoBruto]:
    try:
        nb = nbformat.read(str(caminho), as_version=4)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, nbformat.reader.NotJSONError) as e:
        raise ArquivoParseError(str(caminho), "notebook_parser", e) from e
    except Exception as e:
        # nbformat pode levantar suas próprias exceções de validação para
        # notebooks malformados que não se encaixam nos tipos acima
        raise ArquivoParseError(str(caminho), "notebook_parser", e) from e

    blocos: list[BlocoBruto] = []
    explicacao_atual = None
    ordem = 0

    for cell in nb.get("cells", []):
        origem = "".join(cell.get("source", [])).strip()
        if not origem:
            continue

        if cell.get("cell_type") == "markdown":
            explicacao_atual = origem
            continue

        if cell.get("cell_type") == "code":
            blocos.append(BlocoBruto(
                ordem=ordem,
                titulo=None,
                explicacao=explicacao_atual,
                codigo=origem,
                linguagem=_detectar_linguagem(origem),
            ))
            ordem += 1
            explicacao_atual = None

    return blocos
