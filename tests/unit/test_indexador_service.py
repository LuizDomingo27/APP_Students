"""Testa a regra mais importante da camada de indexação: a falha de um
arquivo nunca pode interromper o processamento dos demais. Usa repositórios
falsos (em memória) para não depender de um banco real.
"""
from contextlib import contextmanager
from unittest.mock import patch

from acervo.core.models import Categoria
from acervo.ingestion.scanner import ArquivoBruto
from acervo.search import indexador_service


@contextmanager
def _cursor_fake():
    yield object()


class FakeCategoriaRepo:
    def upsert(self, cur, categoria: Categoria) -> int:
        return 1


class FakeArquivoRepo:
    def __init__(self, falha_em=None):
        self.falha_em = falha_em or set()
        self.indexados: list[str] = []

    def hash_ja_indexado(self, cur, caminho, hash_):
        return False

    def upsert(self, cur, arquivo):
        if arquivo.caminho in self.falha_em:
            raise RuntimeError(f"falha simulada para {arquivo.caminho}")
        self.indexados.append(arquivo.caminho)
        return len(self.indexados)

    def remover_blocos(self, cur, arquivo_id):
        pass


class FakeBlocoRepo:
    def inserir_muitos(self, cur, blocos):
        pass


class FakeFalhaRepo:
    def __init__(self):
        self.registradas: list[tuple[str, str, str]] = []

    def registrar(self, cur, caminho, etapa, erro):
        self.registradas.append((caminho, etapa, erro))


def _arquivo_bruto(tmp_path, nome, conteudo, tipo_parser="sql"):
    caminho = tmp_path / nome
    caminho.write_text(conteudo, encoding="utf-8")
    return ArquivoBruto(
        caminho_absoluto=caminho,
        caminho_relativo=nome,
        pasta_raiz="Pasta_Teste",
        extensao=".sql",
        tipo_parser=tipo_parser,
        tamanho_bytes=caminho.stat().st_size,
        hash="hash-" + nome,
    )


def _rodar_indexacao(tmp_path, arquivos, falha_em=None):
    arquivo_repo = FakeArquivoRepo(falha_em=falha_em)
    falha_repo = FakeFalhaRepo()

    with patch.object(indexador_service.scanner, "listar_arquivos", return_value=arquivos), \
         patch.object(indexador_service.scanner, "carregar_categorias", return_value={
             "Pasta_Teste": {"categoria": "Teste", "subcategoria": None, "cor": "#fff"}
         }), \
         patch.object(indexador_service, "cursor", _cursor_fake):
        resultado = indexador_service.indexar_tudo(
            categorias_repo=FakeCategoriaRepo(),
            arquivos_repo=arquivo_repo,
            blocos_repo=FakeBlocoRepo(),
            falhas_repo=falha_repo,
        )

    return resultado, arquivo_repo, falha_repo


def test_falha_em_um_arquivo_nao_interrompe_o_lote(tmp_path):
    arquivos = [
        _arquivo_bruto(tmp_path, "bom1.sql", "SELECT 1;"),
        _arquivo_bruto(tmp_path, "com_falha.sql", "SELECT 2;"),
        _arquivo_bruto(tmp_path, "bom2.sql", "SELECT 3;"),
    ]

    resultado, arquivo_repo, falha_repo = _rodar_indexacao(
        tmp_path, arquivos, falha_em={"com_falha.sql"},
    )

    assert resultado.processados == 2
    assert resultado.falhas == 1
    assert arquivo_repo.indexados == ["bom1.sql", "bom2.sql"]
    assert falha_repo.registradas[0][0] == "com_falha.sql"
    assert falha_repo.registradas[0][1] == "desconhecida"  # RuntimeError generico


def test_arquivo_de_tipo_sem_parser_e_apenas_contabilizado(tmp_path):
    arquivos = [_arquivo_bruto(tmp_path, "dados.csv", "a,b\n1,2", tipo_parser=None)]

    resultado, arquivo_repo, _ = _rodar_indexacao(tmp_path, arquivos)

    assert resultado.ignorados_tipo == 1
    assert resultado.processados == 0
    assert arquivo_repo.indexados == []


def test_notebook_corrompido_e_registrado_com_etapa_do_parser(tmp_path):
    caminho = tmp_path / "corrompido.ipynb"
    caminho.write_text("{ json invalido ][", encoding="utf-8")
    arquivo = ArquivoBruto(
        caminho_absoluto=caminho,
        caminho_relativo="corrompido.ipynb",
        pasta_raiz="Pasta_Teste",
        extensao=".ipynb",
        tipo_parser="notebook",
        tamanho_bytes=caminho.stat().st_size,
        hash="hash-corrompido",
    )

    resultado, _, falha_repo = _rodar_indexacao(tmp_path, [arquivo])

    assert resultado.falhas == 1
    assert falha_repo.registradas[0][1] == "notebook_parser"


def test_sanitizar_texto_remove_nul_e_trunca_conteudo_grande():
    from acervo.search.indexador_service import _LIMITE_CAMPO_TEXTO, _sanitizar_texto

    assert _sanitizar_texto(None) is None
    assert _sanitizar_texto("a\x00b") == "ab"

    texto_grande = "x" * (_LIMITE_CAMPO_TEXTO + 100)
    resultado = _sanitizar_texto(texto_grande)

    assert len(resultado) <= _LIMITE_CAMPO_TEXTO + len("\n[... conteúdo truncado ...]")
    assert resultado.startswith("x" * 100)
    assert "truncado" in resultado


def test_arquivo_com_nul_e_texto_gigante_e_indexado_sem_falha(tmp_path):
    from acervo.search.indexador_service import _LIMITE_CAMPO_TEXTO

    caminho = tmp_path / "com_nul.txt"
    conteudo = ("linha com nul \x00 embutido\n" + "y" * (_LIMITE_CAMPO_TEXTO + 500))
    caminho.write_bytes(conteudo.encode("utf-8"))

    arquivo = ArquivoBruto(
        caminho_absoluto=caminho,
        caminho_relativo="com_nul.txt",
        pasta_raiz="Pasta_Teste",
        extensao=".txt",
        tipo_parser="texto",
        tamanho_bytes=caminho.stat().st_size,
        hash="hash-com-nul",
    )

    resultado, arquivo_repo, falha_repo = _rodar_indexacao(tmp_path, [arquivo])

    assert resultado.processados == 1
    assert resultado.falhas == 0
    assert arquivo_repo.indexados == ["com_nul.txt"]
    assert falha_repo.registradas == []
