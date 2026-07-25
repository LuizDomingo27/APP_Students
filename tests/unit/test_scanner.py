import json

from acervo.ingestion import scanner


def test_listar_arquivos_classifica_e_ignora_conforme_extensao(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    categorias = {"Categoria_Teste": {"categoria": "Teste", "subcategoria": None, "cor": "#fff"}}
    (config_dir / "categorias.json").write_text(json.dumps(categorias), encoding="utf-8")

    pasta_conteudo = tmp_path / "Categoria_Teste"
    pasta_conteudo.mkdir()
    (pasta_conteudo / "aula.sql").write_text("SELECT 1;", encoding="utf-8")
    (pasta_conteudo / "dados.csv").write_text("a,b\n1,2", encoding="utf-8")

    monkeypatch.setattr(scanner, "CONFIG_CATEGORIAS", config_dir / "categorias.json")

    arquivos = list(scanner.listar_arquivos(raiz=tmp_path))
    por_nome = {a.caminho_relativo.split("/")[-1]: a for a in arquivos}

    assert por_nome["aula.sql"].tipo_parser == "sql"
    assert por_nome["dados.csv"].tipo_parser is None


def test_pasta_configurada_ausente_nao_quebra_a_varredura(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    categorias = {"Nao_Existe": {"categoria": "Teste", "subcategoria": None, "cor": "#fff"}}
    (config_dir / "categorias.json").write_text(json.dumps(categorias), encoding="utf-8")

    monkeypatch.setattr(scanner, "CONFIG_CATEGORIAS", config_dir / "categorias.json")

    assert list(scanner.listar_arquivos(raiz=tmp_path)) == []
