"""Testes de integração da busca (Fase 2) contra o Neon.

Semeiam um mini-acervo num schema descartável e validam o comportamento
real do Postgres: stemming em português, ranking, filtros, paginação,
busca literal de código e as agregações do dashboard.
"""
import pytest

from acervo.core.models import Arquivo, Bloco, Categoria
from acervo.persistence.db import cursor
from acervo.persistence.repository import (
    ArquivoRepository,
    BlocoRepository,
    BuscaRepository,
    CategoriaRepository,
    EstatisticaRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def acervo_semeado(schema_teste):
    """Duas categorias, dois arquivos e três blocos com conteúdo distinto."""
    categorias_repo = CategoriaRepository(schema_teste)
    arquivos_repo = ArquivoRepository(schema_teste)
    blocos_repo = BlocoRepository(schema_teste)

    with cursor() as cur:
        cat_ds = categorias_repo.upsert(cur, Categoria(
            id=None, nome="Data Science", subcategoria=None, cor="#c9a6ff",
            pasta_raiz="DS_BUSCA_TESTE",
        ))
        cat_sql = categorias_repo.upsert(cur, Categoria(
            id=None, nome="Scripts SQL", subcategoria=None, cor="#8be9fd",
            pasta_raiz="SQL_BUSCA_TESTE",
        ))
        arq_ds = arquivos_repo.upsert(cur, Arquivo(
            id=None, caminho="DS_BUSCA_TESTE/regressao.ipynb", categoria_id=cat_ds,
            extensao=".ipynb", tipo="conteudo", tamanho_bytes=100, hash="h1",
            duplicado_de=None,
        ))
        arq_sql = arquivos_repo.upsert(cur, Arquivo(
            id=None, caminho="SQL_BUSCA_TESTE/consultas.sql", categoria_id=cat_sql,
            extensao=".sql", tipo="conteudo", tamanho_bytes=100, hash="h2",
            duplicado_de=None,
        ))
        blocos_repo.inserir_muitos(cur, [
            Bloco(id=None, arquivo_id=arq_ds, ordem=0,
                  titulo="Regressão linear simples",
                  explicacao="Ajustamos uma regressão linear para prever o preço.",
                  codigo="modelo = LinearRegression()\nmodelo.fit(X, y)", linguagem="python"),
            Bloco(id=None, arquivo_id=arq_ds, ordem=1,
                  titulo="Agrupamento com pandas",
                  explicacao="Agregando as vendas por região.",
                  codigo="df.groupby('regiao')['venda'].sum()", linguagem="python"),
            Bloco(id=None, arquivo_id=arq_sql, ordem=0,
                  titulo="Consultas com janela",
                  explicacao="Uma consulta com função de janela para ranking.",
                  codigo="SELECT rank() OVER (ORDER BY venda DESC) FROM vendas", linguagem="sql"),
        ])

    return {"cat_ds": cat_ds, "cat_sql": cat_sql, "schema": schema_teste}


def test_busca_texto_ignora_acentos_e_flexao(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        # digitado sem acento, deve encontrar "Regressão linear" (unaccent)
        sem_acento, total_sem_acento = repo.buscar_texto(cur, "regressao linear")
        # plural "consultas" deve encontrar "consulta" (stemming)
        plural, total_plural = repo.buscar_texto(cur, "consultas")

    assert total_sem_acento == 1
    assert sem_acento[0].arquivo_caminho == "DS_BUSCA_TESTE/regressao.ipynb"
    assert sem_acento[0].categoria_nome == "Data Science"
    assert sem_acento[0].relevancia > 0

    assert total_plural == 1
    assert plural[0].arquivo_caminho == "SQL_BUSCA_TESTE/consultas.sql"


def test_busca_texto_filtra_por_categoria(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        _, total_sem_filtro = repo.buscar_texto(cur, "consulta OR regressão")
        _, total_so_sql = repo.buscar_texto(
            cur, "consulta OR regressão", categoria_id=acervo_semeado["cat_sql"],
        )

    assert total_sem_filtro == 2
    assert total_so_sql == 1


def test_busca_texto_termo_sem_resultado_nao_levanta_erro(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        resultados, total = repo.buscar_texto(cur, "quantum blockchain !!! ???")

    assert resultados == []
    assert total == 0


def test_busca_codigo_encontra_trecho_literal(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        resultados, total = repo.buscar_codigo(cur, "df.groupby")

    assert total == 1
    assert "df.groupby" in resultados[0].codigo


def test_busca_codigo_escapa_curingas_do_like(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        # "%" literal não existe em nenhum código semeado: deve voltar vazio,
        # e não "casar com tudo" como um curinga não escapado faria
        resultados, total = repo.buscar_codigo(cur, "100%")

    assert total == 0
    assert resultados == []


def test_paginacao_mantem_total_e_fatia(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        pagina1, total1 = repo.buscar_texto(cur, "consulta OR regressão", limite=1, offset=0)
        pagina2, total2 = repo.buscar_texto(cur, "consulta OR regressão", limite=1, offset=1)

    assert total1 == total2 == 2
    assert len(pagina1) == len(pagina2) == 1
    assert pagina1[0].bloco_id != pagina2[0].bloco_id


def test_blocos_do_arquivo_vem_na_ordem(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        blocos = repo.blocos_do_arquivo(cur, "DS_BUSCA_TESTE/regressao.ipynb")

    assert [b.ordem for b in blocos] == [0, 1]
    assert blocos[0].titulo == "Regressão linear simples"


def test_listar_categorias_e_linguagens(acervo_semeado):
    repo = BuscaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        categorias = repo.listar_categorias(cur)
        linguagens = repo.listar_linguagens(cur)

    assert {c.nome for c in categorias} >= {"Data Science", "Scripts SQL"}
    assert linguagens == ["python", "sql"]


def test_resumo_do_acervo(acervo_semeado):
    repo = EstatisticaRepository(acervo_semeado["schema"])
    with cursor() as cur:
        resumo = repo.resumo(cur)

    assert resumo.total_arquivos >= 2
    assert resumo.total_blocos >= 3
    por_nome = {e.categoria_nome: e for e in resumo.por_categoria}
    assert por_nome["Data Science"].total_blocos == 2
    assert por_nome["Scripts SQL"].total_arquivos == 1
