"""Testa as salvaguardas da limpeza de órfãos:

  - arquivo sumido de uma pasta que AINDA existe → é órfão;
  - pasta raiz removida por inteiro → todos os registros são preservados;
  - dry-run (padrão) nunca remove nada.

Usa um repositório falso em memória para não depender de banco real.
"""
from contextlib import contextmanager
from unittest.mock import patch

from acervo.search import limpeza_service


@contextmanager
def _cursor_fake():
    yield object()


class FakeArquivoRepo:
    def __init__(self, caminhos_por_pasta):
        self.caminhos_por_pasta = caminhos_por_pasta
        self.removidos: list[str] = []

    def listar_caminhos_de_varredura(self, cur, pasta_raiz):
        return list(self.caminhos_por_pasta.get(pasta_raiz, []))

    def remover_por_caminhos(self, cur, caminhos):
        self.removidos.extend(caminhos)
        return len(caminhos)


def _rodar(tmp_path, categorias, caminhos_por_pasta, aplicar=False):
    repo = FakeArquivoRepo(caminhos_por_pasta)
    with patch.object(limpeza_service.scanner, "carregar_categorias", return_value=categorias), \
         patch.object(limpeza_service, "cursor", _cursor_fake):
        resultado = limpeza_service.limpar_orfaos(
            raiz=tmp_path, aplicar=aplicar, arquivos_repo=repo,
        )
    return resultado, repo


_CATEGORIAS = {"Pasta_A": {"categoria": "A", "cor": "#fff"}}


def test_arquivo_sumido_de_pasta_existente_e_orfao(tmp_path):
    pasta = tmp_path / "Pasta_A"
    pasta.mkdir()
    (pasta / "presente.sql").write_text("SELECT 1;", encoding="utf-8")

    resultado, _ = _rodar(tmp_path, _CATEGORIAS, {
        "Pasta_A": ["Pasta_A/presente.sql", "Pasta_A/sumido.sql"],
    })

    assert resultado.orfaos == ["Pasta_A/sumido.sql"]
    assert resultado.pastas_preservadas == []


def test_pasta_raiz_removida_preserva_todos_os_registros(tmp_path):
    # a pasta Pasta_A não existe no tmp_path: cenário "conteúdo arquivado no banco"
    resultado, repo = _rodar(tmp_path, _CATEGORIAS, {
        "Pasta_A": ["Pasta_A/aula1.sql", "Pasta_A/aula2.sql"],
    }, aplicar=True)

    assert resultado.orfaos == []
    assert resultado.pastas_preservadas == ["Pasta_A"]
    assert resultado.removidos == 0
    assert repo.removidos == []


def test_dry_run_nao_remove_nada(tmp_path):
    (tmp_path / "Pasta_A").mkdir()

    resultado, repo = _rodar(tmp_path, _CATEGORIAS, {
        "Pasta_A": ["Pasta_A/sumido.sql"],
    }, aplicar=False)

    assert resultado.orfaos == ["Pasta_A/sumido.sql"]
    assert resultado.aplicado is False
    assert resultado.removidos == 0
    assert repo.removidos == []


def test_aplicar_remove_apenas_os_orfaos(tmp_path):
    pasta = tmp_path / "Pasta_A"
    pasta.mkdir()
    (pasta / "presente.sql").write_text("SELECT 1;", encoding="utf-8")

    resultado, repo = _rodar(tmp_path, _CATEGORIAS, {
        "Pasta_A": ["Pasta_A/presente.sql", "Pasta_A/sumido.sql"],
    }, aplicar=True)

    assert resultado.removidos == 1
    assert repo.removidos == ["Pasta_A/sumido.sql"]


def test_subpasta_renomeada_gera_orfaos_dos_caminhos_antigos(tmp_path):
    pasta = tmp_path / "Pasta_A" / "novo_nome"
    pasta.mkdir(parents=True)
    (pasta / "aula.sql").write_text("SELECT 1;", encoding="utf-8")

    resultado, _ = _rodar(tmp_path, _CATEGORIAS, {
        "Pasta_A": ["Pasta_A/nome_antigo/aula.sql"],
    })

    assert resultado.orfaos == ["Pasta_A/nome_antigo/aula.sql"]
