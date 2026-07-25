"""Extrai blocos de scripts .sql.

O arquivo é dividido em blocos separados por linha(s) em branco; linhas de
comentário (`--`) que abrem um bloco viram a "explicação" daquele bloco de
código — reflete como os scripts de aula do acervo costumam ser escritos.
"""
import re
from pathlib import Path

from acervo.core.exceptions import ArquivoParseError
from acervo.ingestion.parsers.base import BlocoBruto

_ENCODINGS_TENTATIVAS = ("utf-8", "latin-1")


def _ler_texto(caminho: Path) -> str:
    ultimo_erro: UnicodeDecodeError | None = None
    for encoding in _ENCODINGS_TENTATIVAS:
        try:
            return caminho.read_text(encoding=encoding)
        except UnicodeDecodeError as e:
            ultimo_erro = e
    raise ultimo_erro  # type: ignore[misc]


def parse(caminho: Path) -> list[BlocoBruto]:
    try:
        texto = _ler_texto(caminho)
    except (OSError, UnicodeDecodeError) as e:
        raise ArquivoParseError(str(caminho), "sql_parser", e) from e

    blocos: list[BlocoBruto] = []
    for ordem, bruto in enumerate(b.strip() for b in re.split(r"\n\s*\n+", texto)):
        if not bruto:
            continue

        linhas = bruto.splitlines()
        comentarios = [l for l in linhas if l.strip().startswith("--")]
        codigo = "\n".join(l for l in linhas if not l.strip().startswith("--")).strip()
        explicacao = "\n".join(c.lstrip("- ").strip() for c in comentarios) or None

        if not codigo and not explicacao:
            continue

        blocos.append(BlocoBruto(
            ordem=ordem,
            titulo=None,
            explicacao=explicacao,
            codigo=codigo or None,
            linguagem="sql",
        ))

    return blocos
