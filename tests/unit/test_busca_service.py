"""Testes unitários do serviço de busca — sem banco.

Um repositório falso captura os argumentos passados; o que se valida aqui é
o contrato do serviço: validação de input, tradução página→offset e escolha
da variante (texto × código).
"""
import pytest

from acervo.core.exceptions import BuscaError
from acervo.core.models import ResultadoBusca
from acervo.search import busca_service


class RepoFalso:
    def __init__(self, resultados=None, total=0):
        self.resultados = resultados or []
        self.total = total
        self.chamadas = []

    def buscar_texto(self, cur, termo, **kwargs):
        self.chamadas.append(("texto", termo, kwargs))
        return self.resultados, self.total

    def buscar_codigo(self, cur, trecho, **kwargs):
        self.chamadas.append(("codigo", trecho, kwargs))
        return self.resultados, self.total


@pytest.fixture(autouse=True)
def cursor_falso(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _cursor():
        yield object()

    monkeypatch.setattr(busca_service, "cursor", _cursor)


def _resultado(bloco_id=1):
    return ResultadoBusca(
        bloco_id=bloco_id, arquivo_caminho="Pasta/a.sql", categoria_nome="SQL",
        subcategoria=None, titulo=None, explicacao="exemplo", codigo=None,
        linguagem="sql", relevancia=0.5,
    )


def test_termo_vazio_e_rejeitado():
    with pytest.raises(BuscaError, match="termo"):
        busca_service.buscar("   ", repo=RepoFalso())


def test_modo_invalido_e_rejeitado():
    with pytest.raises(BuscaError, match="Modo"):
        busca_service.buscar("pandas", modo="regex", repo=RepoFalso())


def test_pagina_e_limite_invalidos_sao_rejeitados():
    with pytest.raises(BuscaError, match="página"):
        busca_service.buscar("pandas", pagina=0, repo=RepoFalso())
    with pytest.raises(BuscaError, match="limite"):
        busca_service.buscar("pandas", limite=0, repo=RepoFalso())
    with pytest.raises(BuscaError, match="limite"):
        busca_service.buscar("pandas", limite=busca_service.LIMITE_MAXIMO + 1, repo=RepoFalso())


def test_modo_texto_usa_variante_texto_e_traduz_pagina_em_offset():
    repo = RepoFalso(resultados=[_resultado()], total=41)

    pagina = busca_service.buscar("regressão linear", pagina=3, limite=20, repo=repo)

    (variante, termo, kwargs), = repo.chamadas
    assert variante == "texto"
    assert termo == "regressão linear"
    assert kwargs["offset"] == 40  # (página 3 - 1) * 20
    assert kwargs["limite"] == 20
    assert pagina.total == 41
    assert pagina.pagina == 3
    assert pagina.resultados[0].bloco_id == 1


def test_modo_codigo_usa_variante_codigo_e_repassa_filtros():
    repo = RepoFalso()

    busca_service.buscar("df.groupby", modo="codigo", categoria_id=7, linguagem="python", repo=repo)

    (variante, termo, kwargs), = repo.chamadas
    assert variante == "codigo"
    assert termo == "df.groupby"
    assert kwargs["categoria_id"] == 7
    assert kwargs["linguagem"] == "python"


def test_falha_de_infraestrutura_vira_busca_error():
    from acervo.core.exceptions import ConexaoBancoError

    class RepoQuebrado:
        def buscar_texto(self, cur, termo, **kwargs):
            raise ConexaoBancoError("banco fora do ar")

    with pytest.raises(BuscaError, match="banco fora do ar"):
        busca_service.buscar("pandas", repo=RepoQuebrado())


def test_conteudo_do_arquivo_exige_caminho():
    with pytest.raises(BuscaError, match="caminho"):
        busca_service.conteudo_do_arquivo("  ")
