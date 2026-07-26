"""Testes dos helpers puros da UI (app/componentes.py) — sem subir Streamlit."""
from datetime import datetime

from acervo.core.models import Bloco, ConteudoCategoria
from app.componentes import (
    PAGINA_ADMIN,
    PAGINAS_ABERTAS,
    cartao_metrica_html,
    chip_html,
    formatar_data,
    formatar_numero,
    opcoes_de_navegacao,
    previa_de_codigo,
    primeiro_nome,
    resumir,
    rotulo_categoria,
    rotulo_conteudo,
    rotulos_de_conteudo,
    titulo_do_bloco,
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


def test_rotulo_conteudo_remove_a_pasta_raiz_e_encurta_caminhos_fundos():
    fundo = "Estatistica_DS/Livro/Slides/Regressao.pdf"
    assert rotulo_conteudo("Estatistica_DS/estatistica.ipynb", "Estatistica_DS") == "estatistica.ipynb"
    assert rotulo_conteudo(fundo, "Estatistica_DS") == "…/Regressao.pdf"
    assert rotulo_conteudo(fundo, "Estatistica_DS", niveis=2) == "…/Slides/Regressao.pdf"
    # niveis=0 (ou além da profundidade) devolve o caminho relativo inteiro
    assert rotulo_conteudo(fundo, "Estatistica_DS", niveis=0) == "Livro/Slides/Regressao.pdf"
    assert rotulo_conteudo(fundo, "Estatistica_DS", niveis=9) == "Livro/Slides/Regressao.pdf"
    # separador do Windows e raiz que não bate com o caminho não quebram o rótulo
    assert rotulo_conteudo("SQL\\aula.sql", "SQL") == "aula.sql"
    assert rotulo_conteudo("Outra/aula.sql", "SQL") == "…/aula.sql"


def _conteudo(caminho, pasta_raiz="Cat", total_blocos=3):
    return ConteudoCategoria(caminho=caminho, pasta_raiz=pasta_raiz, total_blocos=total_blocos)


def test_rotulos_de_conteudo_mapeiam_para_o_caminho_e_contam_blocos():
    rotulos = rotulos_de_conteudo([_conteudo("Cat/aula.sql", total_blocos=1),
                                   _conteudo("Cat/notas.ipynb", total_blocos=12)])

    assert rotulos == {"aula.sql · 1 bloco": "Cat/aula.sql",
                       "notas.ipynb · 12 blocos": "Cat/notas.ipynb"}


def test_rotulos_de_conteudo_mostram_so_o_nome_do_arquivo_quando_ja_basta():
    rotulos = rotulos_de_conteudo([_conteudo("Cat/upload_cat/Capítulo 01.ipynb"),
                                   _conteudo("Cat/upload_cat/Capítulo 02.ipynb")])

    assert list(rotulos) == ["…/Capítulo 01.ipynb · 3 blocos", "…/Capítulo 02.ipynb · 3 blocos"]


def test_rotulos_de_conteudo_sobem_um_nivel_ate_ficarem_unicos():
    conteudos = [_conteudo("Cat/mod1/aula/querys.txt"),
                 _conteudo("Cat/mod2/aula/querys.txt"),
                 _conteudo("Cat/notas.sql")]

    rotulos = rotulos_de_conteudo(conteudos)

    # nenhum arquivo pode sumir por colisão de rótulo
    assert len(rotulos) == 3
    assert set(rotulos.values()) == {c.caminho for c in conteudos}
    # "querys.txt" colide e "aula/querys.txt" também: sobra o caminho relativo
    assert rotulos["mod1/aula/querys.txt · 3 blocos"] == "Cat/mod1/aula/querys.txt"
    assert rotulos["notas.sql · 3 blocos"] == "Cat/notas.sql"


def _bloco(titulo=None, explicacao=None, codigo=None):
    return Bloco(id=1, arquivo_id=1, ordem=0, titulo=titulo, explicacao=explicacao,
                 codigo=codigo, linguagem=None)


def test_titulo_do_bloco_cai_para_explicacao_e_depois_para_codigo():
    assert titulo_do_bloco(_bloco(titulo="Regressão")) == "Regressão"
    assert titulo_do_bloco(_bloco(titulo="   ", explicacao="Ajuste do modelo")) == "Ajuste do modelo"
    assert titulo_do_bloco(_bloco(codigo="df.groupby('x')")) == "df.groupby('x')"
    assert titulo_do_bloco(_bloco()) == "(bloco sem título)"


def test_titulo_do_bloco_pula_faixas_de_comentario_do_notebook():
    codigo = "########################\n# MANUAL DE ANÁLISE\n########\ndf = pd.read_csv('a.csv')"
    assert titulo_do_bloco(_bloco(codigo=codigo)) == "MANUAL DE ANÁLISE"
    # linha só de decoração não vira título
    assert titulo_do_bloco(_bloco(codigo="# ====== #\n")) == "(bloco sem título)"


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


def test_navegacao_esconde_usuarios_de_quem_nao_e_admin():
    assert opcoes_de_navegacao(False) == list(PAGINAS_ABERTAS)
    assert PAGINA_ADMIN not in opcoes_de_navegacao(False)


def test_navegacao_do_admin_acrescenta_usuarios_no_fim():
    opcoes = opcoes_de_navegacao(True)
    assert opcoes[: len(PAGINAS_ABERTAS)] == list(PAGINAS_ABERTAS)
    assert opcoes[-1] == PAGINA_ADMIN


def test_formatar_data():
    assert formatar_data(datetime(2026, 3, 9, 14, 30)) == "09/03/2026"
    assert formatar_data(None) == "—"


def test_primeiro_nome():
    assert primeiro_nome("Ana Silva Souza") == "Ana"
    assert primeiro_nome("Ana") == "Ana"
    assert primeiro_nome("  ") == "  "
