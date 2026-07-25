"""Testa o serviço de upload: validação de extensão, regras de duplicata e
gravação com origem='upload'. Repositórios falsos em memória — sem banco.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from acervo.core.exceptions import UploadError
from acervo.core.models import Categoria
from acervo.search import upload_service


@contextmanager
def _cursor_fake():
    yield object()


CATEGORIA = Categoria(id=7, nome="SQL Server", subcategoria=None, cor="#fff", pasta_raiz="SQL_SERVER")


class FakeArquivoRepo:
    def __init__(self, hash_por_caminho=None):
        self.hashes = dict(hash_por_caminho or {})
        self.upserts = []

    def hash_por_caminho(self, cur, caminho):
        return self.hashes.get(caminho)

    def caminho_com_hash(self, cur, hash_):
        for caminho, h in self.hashes.items():
            if h == hash_:
                return caminho
        return None

    def upsert(self, cur, arquivo):
        self.upserts.append(arquivo)
        return 1

    def remover_blocos(self, cur, arquivo_id):
        pass


class FakeBlocoRepo:
    def __init__(self):
        self.inseridos = []

    def inserir_muitos(self, cur, blocos):
        self.inseridos.extend(blocos)


def _adicionar(nome, dados, arquivo_repo=None):
    arquivo_repo = arquivo_repo or FakeArquivoRepo()
    bloco_repo = FakeBlocoRepo()
    with patch.object(upload_service, "cursor", _cursor_fake):
        resultado = upload_service.adicionar_conteudo(
            nome, dados, CATEGORIA,
            arquivos_repo=arquivo_repo, blocos_repo=bloco_repo,
        )
    return resultado, arquivo_repo, bloco_repo


def _hash(dados: bytes) -> str:
    import hashlib
    return hashlib.sha256(dados).hexdigest()


def test_extensao_nao_suportada_levanta_upload_error():
    with pytest.raises(UploadError, match="não suportada"):
        _adicionar("dados.csv", b"a,b\n1,2")


def test_arquivo_novo_e_adicionado_com_origem_upload():
    resultado, arquivo_repo, bloco_repo = _adicionar("consulta.sql", b"SELECT 1;")

    assert resultado.status == "adicionado"
    assert resultado.caminho == "uploads/SQL_SERVER/consulta.sql"
    assert resultado.total_blocos == len(bloco_repo.inseridos) > 0

    gravado = arquivo_repo.upserts[0]
    assert gravado.origem == "upload"
    assert gravado.categoria_id == CATEGORIA.id
    assert gravado.caminho == "uploads/SQL_SERVER/consulta.sql"


def test_mesmo_caminho_e_hash_nao_regrava():
    dados = b"SELECT 1;"
    repo = FakeArquivoRepo({"uploads/SQL_SERVER/consulta.sql": _hash(dados)})

    resultado, arquivo_repo, _ = _adicionar("consulta.sql", dados, arquivo_repo=repo)

    assert resultado.status == "sem_alteracao"
    assert arquivo_repo.upserts == []


def test_conteudo_identico_em_outro_caminho_e_reportado_como_duplicado():
    dados = b"SELECT 1;"
    repo = FakeArquivoRepo({"SQL_SERVER/aula/original.sql": _hash(dados)})

    resultado, arquivo_repo, _ = _adicionar("copia.sql", dados, arquivo_repo=repo)

    assert resultado.status == "duplicado"
    assert resultado.duplicado_de == "SQL_SERVER/aula/original.sql"
    assert arquivo_repo.upserts == []


def test_mesmo_caminho_com_conteudo_novo_e_atualizado():
    repo = FakeArquivoRepo({"uploads/SQL_SERVER/consulta.sql": "hash-antigo"})

    resultado, arquivo_repo, _ = _adicionar("consulta.sql", b"SELECT 2;", arquivo_repo=repo)

    assert resultado.status == "atualizado"
    assert len(arquivo_repo.upserts) == 1


def test_nome_com_caminho_usa_apenas_o_nome_base():
    resultado, _, _ = _adicionar("C:\\Users\\alguem\\Desktop\\consulta.sql", b"SELECT 1;")
    assert resultado.caminho == "uploads/SQL_SERVER/consulta.sql"


def test_criar_categoria_gera_pasta_raiz_com_slug():
    class FakeCategoriaRepo:
        def upsert(self, cur, categoria):
            self.recebida = categoria
            return 42

    repo = FakeCategoriaRepo()
    with patch.object(upload_service, "cursor", _cursor_fake):
        categoria = upload_service.criar_categoria(
            "Machine Learning", "Módulo 3", "#123456", categorias_repo=repo,
        )

    assert categoria.id == 42
    assert categoria.pasta_raiz == "upload_machine_learning_modulo_3"
    assert repo.recebida.nome == "Machine Learning"


def test_criar_categoria_sem_nome_falha():
    with pytest.raises(UploadError, match="nome"):
        upload_service.criar_categoria("  ", None, "#fff")
