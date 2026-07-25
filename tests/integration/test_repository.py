"""Testes de integração reais contra o Neon.

Só rodam se DATABASE_URL estiver configurado (ver .env.example); caso
contrário são pulados automaticamente pela fixture `schema_teste`.
Cada execução cria e depois derruba um schema descartável, nunca tocando
dados de produção.
"""
import pytest

from acervo.core.models import Arquivo, Bloco, Categoria
from acervo.persistence.db import cursor
from acervo.persistence.repository import ArquivoRepository, BlocoRepository, CategoriaRepository

pytestmark = pytest.mark.integration


def test_upsert_categoria_arquivo_bloco_e_busca_textual(schema_teste):
    categorias_repo = CategoriaRepository(schema_teste)
    arquivos_repo = ArquivoRepository(schema_teste)
    blocos_repo = BlocoRepository(schema_teste)

    with cursor() as cur:
        categoria_id = categorias_repo.upsert(cur, Categoria(
            id=None, nome="PostgreSQL", subcategoria=None, cor="#c9a6ff",
            pasta_raiz="POSTGREES_TESTE",
        ))
        arquivo_id = arquivos_repo.upsert(cur, Arquivo(
            id=None, caminho="POSTGREES_TESTE/exemplo.sql", categoria_id=categoria_id,
            extensao=".sql", tipo="conteudo", tamanho_bytes=42, hash="abc123",
            duplicado_de=None,
        ))
        blocos_repo.inserir_muitos(cur, [
            Bloco(id=None, arquivo_id=arquivo_id, ordem=0, titulo=None,
                  explicacao="Consulta parâmetros de conexão",
                  codigo="select * from pg_settings", linguagem="sql"),
        ])

    with cursor() as cur:
        cur.execute(
            f'SELECT explicacao, ts_rank(texto_busca, query) AS relevancia '
            f'FROM "{schema_teste}".blocos, '
            f'to_tsquery(\'{schema_teste}.portugues_unaccent\', %s) query '
            f'WHERE texto_busca @@ query',
            ("parâmetros",),
        )
        linhas = cur.fetchall()

    assert len(linhas) == 1
    assert "parâmetros" in linhas[0][0].lower()


def test_hash_ja_indexado_evita_reprocessamento(schema_teste):
    categorias_repo = CategoriaRepository(schema_teste)
    arquivos_repo = ArquivoRepository(schema_teste)

    with cursor() as cur:
        categoria_id = categorias_repo.upsert(cur, Categoria(
            id=None, nome="Teste", subcategoria=None, cor="#fff",
            pasta_raiz="PASTA_TESTE_HASH",
        ))
        arquivos_repo.upsert(cur, Arquivo(
            id=None, caminho="PASTA_TESTE_HASH/a.sql", categoria_id=categoria_id,
            extensao=".sql", tipo="conteudo", tamanho_bytes=10, hash="hash-fixo",
            duplicado_de=None,
        ))

    with cursor() as cur:
        assert arquivos_repo.hash_ja_indexado(cur, "PASTA_TESTE_HASH/a.sql", "hash-fixo") is True
        assert arquivos_repo.hash_ja_indexado(cur, "PASTA_TESTE_HASH/a.sql", "hash-diferente") is False


def test_falha_indexacao_e_registrada(schema_teste):
    from acervo.persistence.repository import FalhaRepository

    falhas_repo = FalhaRepository(schema_teste)
    with cursor() as cur:
        falhas_repo.registrar(cur, "Pasta/arquivo_ruim.pdf", "pdf_parser", "arquivo corrompido")

    with cursor() as cur:
        # filtra pelo próprio arquivo: o schema é compartilhado pela sessão de
        # testes e outros testes de integração também registram falhas
        cur.execute(
            f'SELECT etapa, erro FROM "{schema_teste}".falhas_indexacao '
            f'WHERE arquivo_caminho = %s',
            ("Pasta/arquivo_ruim.pdf",),
        )
        linhas = cur.fetchall()

    assert linhas == [("pdf_parser", "arquivo corrompido")]
