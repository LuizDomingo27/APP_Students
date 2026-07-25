"""Testes dos helpers puros da UI (app/componentes.py) — sem subir Streamlit."""
from app.componentes import (
    cartao_metrica_html,
    chip_html,
    formatar_numero,
    previa_de_codigo,
    resumir,
    rotulo_categoria,
    total_de_paginas,
)


def test_resumir_achata_quebras_de_linha_e_corta_com_reticencias():
    assert resumir("linha um\nlinha  dois") == "linha um linha dois"
    longo = "palavra " * 100
    resultado = resumir(longo, maximo=50)
    assert len(resultado) <= 51  # 50 + reticência
    assert resultado.endswith("…")


def test_resumir_texto_curto_fica_intacto():
    assert resumir("curto") == "curto"


def test_formatar_numero_no_padrao_brasileiro():
    assert formatar_numero(6595) == "6.595"
    assert formatar_numero(505) == "505"
    assert formatar_numero(1234567) == "1.234.567"


def test_total_de_paginas():
    assert total_de_paginas(0, 10) == 0
    assert total_de_paginas(10, 10) == 1
    assert total_de_paginas(11, 10) == 2
    assert total_de_paginas(25, 10) == 3


def test_rotulo_categoria_com_e_sem_subcategoria():
    assert rotulo_categoria("Databricks", "Módulo 1") == "Databricks · Módulo 1"
    assert rotulo_categoria("Estatística", None) == "Estatística"


def test_previa_de_codigo_limita_linhas():
    codigo = "\n".join(f"linha {i}" for i in range(30))
    previa = previa_de_codigo(codigo, max_linhas=5)
    assert previa.splitlines()[:5] == [f"linha {i}" for i in range(5)]
    assert previa.endswith("…")
    # códigos curtos ficam intactos
    assert previa_de_codigo("a = 1") == "a = 1"


def test_chip_html_escapa_texto_e_usa_a_cor():
    html_chip = chip_html("<b>SQL</b>", "#a78bfa")
    assert "&lt;b&gt;SQL&lt;/b&gt;" in html_chip
    assert "#a78bfa" in html_chip


def test_cartao_metrica_formata_valor():
    html_cartao = cartao_metrica_html("Blocos", 6595, "#7dd3fc")
    assert "6.595" in html_cartao
    assert "Blocos" in html_cartao
    assert "--cor-metrica:#7dd3fc" in html_cartao
