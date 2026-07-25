from acervo.ingestion.parsers import text_parser


def test_arquivo_md_vira_explicacao(tmp_path):
    caminho = tmp_path / "notas.md"
    caminho.write_text("# Estatística descritiva\nMédia e mediana.", encoding="utf-8")

    blocos = text_parser.parse(caminho)

    assert len(blocos) == 1
    assert blocos[0].explicacao.startswith("# Estatística")
    assert blocos[0].codigo is None


def test_arquivo_py_vira_codigo(tmp_path):
    caminho = tmp_path / "script.py"
    caminho.write_text("import pandas as pd", encoding="utf-8")

    blocos = text_parser.parse(caminho)

    assert blocos[0].codigo == "import pandas as pd"
    assert blocos[0].linguagem == "python"


def test_arquivo_vazio_nao_gera_blocos(tmp_path):
    caminho = tmp_path / "vazio.txt"
    caminho.write_text("", encoding="utf-8")

    assert text_parser.parse(caminho) == []
