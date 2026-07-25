import pytest
from pypdf import PdfWriter

from acervo.core.exceptions import ArquivoParseError
from acervo.ingestion.parsers import pdf_parser


def test_pdf_corrompido_gera_erro_tratado(tmp_path):
    caminho = tmp_path / "corrompido.pdf"
    caminho.write_bytes(b"isso nao e um pdf valido")

    with pytest.raises(ArquivoParseError):
        pdf_parser.parse(caminho)


def test_pdf_sem_texto_nao_gera_blocos(tmp_path):
    caminho = tmp_path / "em_branco.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(caminho, "wb") as f:
        writer.write(f)

    assert pdf_parser.parse(caminho) == []
