"""Extrai texto de PDFs, um bloco por página.

Uma página individual corrompida não derruba o PDF inteiro: é pulada e
registrada em log — só um PDF que não abre de jeito nenhum vira erro fatal
do arquivo (ArquivoParseError).
"""
import logging
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from acervo.core.exceptions import ArquivoParseError
from acervo.ingestion.parsers.base import BlocoBruto

logger = logging.getLogger("acervo.parsers.pdf")


def parse(caminho: Path) -> list[BlocoBruto]:
    try:
        leitor = PdfReader(str(caminho))
    except (PdfReadError, OSError) as e:
        raise ArquivoParseError(str(caminho), "pdf_parser", e) from e

    blocos: list[BlocoBruto] = []
    for ordem, pagina in enumerate(leitor.pages):
        try:
            texto = (pagina.extract_text() or "").strip()
        except Exception as e:
            logger.warning("Pulando página %s de '%s': %s", ordem + 1, caminho, e)
            continue

        if not texto:
            continue

        blocos.append(BlocoBruto(
            ordem=ordem,
            titulo=f"Página {ordem + 1}",
            explicacao=texto,
            codigo=None,
            linguagem=None,
        ))

    return blocos
