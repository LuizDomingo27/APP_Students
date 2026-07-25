from acervo.ingestion.parsers import sql_parser


def test_separa_blocos_por_linha_em_branco(tmp_path):
    caminho = tmp_path / "exemplo.sql"
    caminho.write_text(
        "-- lista clientes ativos\nSELECT * FROM clientes WHERE ativo = true;\n\n"
        "-- conta pedidos\nSELECT COUNT(*) FROM pedidos;",
        encoding="utf-8",
    )

    blocos = sql_parser.parse(caminho)

    assert len(blocos) == 2
    assert blocos[0].explicacao == "lista clientes ativos"
    assert "SELECT * FROM clientes" in blocos[0].codigo
    assert blocos[1].explicacao == "conta pedidos"
    assert all(b.linguagem == "sql" for b in blocos)


def test_arquivo_vazio_nao_gera_blocos(tmp_path):
    caminho = tmp_path / "vazio.sql"
    caminho.write_text("\n\n   \n", encoding="utf-8")

    assert sql_parser.parse(caminho) == []


def test_encoding_latin1_e_lido_sem_erro(tmp_path):
    caminho = tmp_path / "latin1.sql"
    caminho.write_bytes("-- descrição\nSELECT 1;".encode("latin-1"))

    blocos = sql_parser.parse(caminho)

    assert len(blocos) == 1
    assert "SELECT 1" in blocos[0].codigo
