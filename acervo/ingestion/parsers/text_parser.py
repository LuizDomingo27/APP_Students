"""Extrai um bloco único de arquivos de texto simples (.txt, .md, .py, .js).

Markdown vira "explicação" (é texto para ler); .py/.js/.txt viram "código"
(é conteúdo para copiar/executar).
"""
from pathlib import Path

from acervo.core.exceptions import ArquivoParseError
from acervo.ingestion.parsers.base import BlocoBruto

_LINGUAGEM_POR_EXTENSAO = {".py": "python", ".js": "javascript", ".sql": "sql"}


def parse(caminho: Path) -> list[BlocoBruto]:
    try:
        texto = caminho.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as e:
        raise ArquivoParseError(str(caminho), "text_parser", e) from e

    if not texto:
        return []

    ext = caminho.suffix.lower()
    eh_markdown = ext == ".md"

    return [BlocoBruto(
        ordem=0,
        titulo=None,
        explicacao=texto if eh_markdown else None,
        codigo=None if eh_markdown else texto,
        linguagem=None if eh_markdown else _LINGUAGEM_POR_EXTENSAO.get(ext),
    )]
