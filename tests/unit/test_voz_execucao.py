"""Testes da execução dos comandos de voz (app/voz.py).

O que se verifica aqui é a **tradução comando → `session_state`**: dizer "modo
código" tem que deixar o estado exatamente como deixaria o clique no botão.
Como em `test_sessao.py`, o `session_state` funciona fora do `streamlit run`,
então nada disso precisa de servidor — nem de microfone.

Filtros (categoria/linguagem/conteúdo) ficam de fora: eles perguntam ao banco
quais opções existem, e isso é território dos testes de integração.
"""
import pytest
import streamlit as st

from acervo.voz import comandos as cmd
from app import componentes as comp
from app import voz


@pytest.fixture(autouse=True)
def _sessao_limpa():
    st.session_state.clear()
    yield
    st.session_state.clear()


def _executar(frase: str, *, eh_admin: bool = False):
    comando = cmd.interpretar(frase)
    assert comando is not None, f"“{frase}” não foi interpretada"
    return voz._executar(comando, eh_admin=eh_admin)


# ---------------------------------------------------------------- navegação

def test_navegar_escreve_a_pagina_da_navbar():
    nivel, _ = _executar("ir para o dashboard")
    assert nivel == "ok"
    assert st.session_state["nav_paginas"] == cmd.PAGINA_DASHBOARD


def test_navegar_fecha_o_menu_da_conta():
    """Trocar de página fechava a conta pelo clique; por voz também fecha."""
    st.session_state["mostrar_conta"] = True
    _executar("abrir dashboard")
    assert st.session_state["mostrar_conta"] is False


def test_pagina_de_usuarios_e_recusada_para_quem_nao_e_admin():
    nivel, mensagem = _executar("usuários", eh_admin=False)
    assert nivel == "aviso"
    assert "administradores" in mensagem
    assert "nav_paginas" not in st.session_state


def test_pagina_de_usuarios_liberada_para_admin():
    nivel, _ = _executar("usuários", eh_admin=True)
    assert nivel == "ok"
    assert st.session_state["nav_paginas"] == cmd.PAGINA_USUARIOS


# -------------------------------------------------------------------- busca

def test_buscar_preenche_o_campo_volta_para_a_busca_e_zera_a_paginacao():
    st.session_state["pagina_busca"] = 4
    nivel, _ = _executar("buscar regressão linear")
    assert nivel == "ok"
    assert st.session_state["termo_busca"] == "regressão linear"
    assert st.session_state["nav_paginas"] == cmd.PAGINA_BUSCA
    assert st.session_state["pagina_busca"] == 1


def test_modo_troca_o_segmented_control_da_busca():
    _executar("modo código")
    assert st.session_state["modo_busca"] == cmd.MODO_CODIGO
    _executar("modo texto")
    assert st.session_state["modo_busca"] == cmd.MODO_TEXTO


def test_limpar_filtros_usa_os_rotulos_que_os_dropdowns_aceitam():
    """Valor fora da lista do selectbox derruba a página — tem que ser o rótulo."""
    st.session_state["filtro_categoria"] = "Databricks"
    st.session_state["filtro_linguagem"] = "python"
    _executar("limpar filtros")
    assert st.session_state["filtro_categoria"] == comp.FILTRO_TODAS
    assert st.session_state["filtro_linguagem"] == comp.FILTRO_TODAS
    assert st.session_state["filtro_conteudo"] == comp.FILTRO_TODO_CONTEUDO


def test_limpar_tudo_apaga_termo_e_filtros():
    st.session_state["termo_busca"] = "regressão"
    st.session_state["filtro_categoria"] = "Databricks"
    _executar("limpar tudo")
    assert st.session_state["termo_busca"] == ""
    assert st.session_state["filtro_categoria"] == comp.FILTRO_TODAS


# ---------------------------------------------------------------- paginação

@pytest.mark.parametrize("valor,atual,total,esperado", [
    (cmd.PROXIMA, 1, 3, 2),
    (cmd.PROXIMA, 3, 3, None),      # já está na última
    (cmd.ANTERIOR, 2, 3, 1),
    (cmd.ANTERIOR, 1, 3, None),     # já está na primeira
    ("2", 1, 3, 2),
    ("9", 1, 3, None),              # além do fim
    ("0", 1, 3, None),
    (cmd.PROXIMA, 1, 0, None),      # sem resultados
])
def test_nova_pagina_respeita_as_bordas(valor, atual, total, esperado):
    assert voz.nova_pagina(valor, atual, total) == esperado


def test_paginar_por_voz_avanca_dentro_do_total_publicado_pela_busca():
    st.session_state[voz.TOTAL_PAGINAS] = 3
    st.session_state["pagina_busca"] = 1
    nivel, mensagem = _executar("próxima página")
    assert nivel == "ok"
    assert st.session_state["pagina_busca"] == 2
    assert "2 de 3" in mensagem


def test_paginar_alem_do_fim_avisa_e_nao_mexe_no_estado():
    st.session_state[voz.TOTAL_PAGINAS] = 2
    st.session_state["pagina_busca"] = 2
    nivel, mensagem = _executar("próxima página")
    assert nivel == "aviso"
    assert "última" in mensagem
    assert st.session_state["pagina_busca"] == 2


def test_paginar_sem_busca_na_tela_avisa():
    nivel, _ = _executar("próxima página")
    assert nivel == "aviso"


# ----------------------------------------------------------- abrir resultado

def test_abrir_pede_o_indice_e_a_busca_converte_para_base_zero():
    _executar("abrir o segundo resultado")
    assert st.session_state[voz.ABRIR_INDICE] == 2
    assert voz.indice_para_abrir(total=10) == 1


def test_abrir_o_ultimo_resultado():
    _executar("abrir o último resultado")
    assert voz.indice_para_abrir(total=7) == 6


def test_abrir_alem_do_que_existe_avisa_e_nao_abre():
    _executar("abrir resultado 9")
    assert voz.indice_para_abrir(total=3) is None
    assert st.session_state[voz.ULTIMO][0] == "aviso"


def test_pedido_de_abertura_e_consumido_uma_vez_so():
    """Senão o diálogo reabre sozinho no rerun seguinte, já fechado pela pessoa."""
    _executar("abrir o primeiro")
    assert voz.indice_para_abrir(total=5) == 0
    assert voz.indice_para_abrir(total=5) is None


def test_descartar_abertura_avisa_quando_nao_ha_lista():
    _executar("abrir o primeiro")
    voz.descartar_abertura("sem resultados")
    assert st.session_state[voz.ULTIMO] == ("aviso", "sem resultados")
    assert voz.ABRIR_INDICE not in st.session_state


def test_descartar_abertura_sem_pedido_pendente_nao_inventa_aviso():
    voz.descartar_abertura("sem resultados")
    assert voz.ULTIMO not in st.session_state


# ------------------------------------------------------------------- conta

def test_trocar_senha_abre_o_painel_da_conta():
    _executar("trocar minha senha")
    assert st.session_state["mostrar_conta"] is True


def test_sair_e_sinalizado_para_quem_chamou_encerrar_a_sessao():
    nivel, _ = _executar("encerrar sessão")
    assert nivel == "sair"


# ---------------------------------------------------- ciclo do campo de texto

def test_receber_guarda_a_frase_e_esvazia_o_campo():
    """Esvaziar é o que permite repetir o mesmo comando duas vezes seguidas."""
    st.session_state[voz.COMANDO] = "  próxima página  "
    voz._receber()
    assert st.session_state[voz.PENDENTE] == "próxima página"
    assert st.session_state[voz.COMANDO] == ""


def test_receber_ignora_campo_vazio():
    st.session_state[voz.COMANDO] = "   "
    voz._receber()
    assert voz.PENDENTE not in st.session_state


def test_processar_pendente_executa_e_consome():
    st.session_state[voz.PENDENTE] = "modo código"
    voz.processar_pendente(eh_admin=False)
    assert st.session_state["modo_busca"] == cmd.MODO_CODIGO
    assert voz.PENDENTE not in st.session_state
    assert st.session_state[voz.ULTIMO][0] == "ok"


def test_frase_nao_reconhecida_avisa_sem_mexer_em_nada():
    st.session_state[voz.PENDENTE] = "hoje o tempo está bom"
    voz.processar_pendente(eh_admin=False)
    nivel, mensagem = st.session_state[voz.ULTIMO]
    assert nivel == "aviso"
    assert "Não entendi" in mensagem
    assert "nav_paginas" not in st.session_state


def test_processar_sem_pendencia_nao_faz_nada():
    voz.processar_pendente(eh_admin=False)
    assert voz.ULTIMO not in st.session_state
