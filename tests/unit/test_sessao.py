"""Testes do estado de sessão da interface (app/sessao.py).

O `session_state` do Streamlit funciona fora do `streamlit run` (em "bare
mode"), então dá para exercitar estas regras sem subir servidor nenhum — o
que importa aqui é o freio de tentativas e quem o app acha que está logado.
"""
import pytest
import streamlit as st

from acervo.core.models import Usuario
from app import sessao

AGORA = 1_000.0


@pytest.fixture(autouse=True)
def _sessao_limpa():
    st.session_state.clear()
    yield
    st.session_state.clear()


def _usuario(**kwargs) -> Usuario:
    campos = {
        "id": 1, "nome": "Ana Silva", "email": "ana@exemplo.com",
        "papel": "usuario", "status": "aprovado",
    }
    return Usuario(**{**campos, **kwargs})


# ------------------------------------------------------------- quem está logado

def test_sem_sessao_nao_ha_usuario_nem_privilegio():
    assert sessao.usuario_atual() is None
    assert sessao.eh_admin() is False
    assert sessao.precisa_trocar_senha() is False


def test_iniciar_e_encerrar_sessao():
    sessao.iniciar_sessao(_usuario())
    assert sessao.usuario_atual().email == "ana@exemplo.com"

    sessao.encerrar_sessao()
    assert sessao.usuario_atual() is None


def test_eh_admin_so_para_admin():
    sessao.iniciar_sessao(_usuario())
    assert sessao.eh_admin() is False

    sessao.iniciar_sessao(_usuario(papel="admin"))
    assert sessao.eh_admin() is True


def test_senha_temporaria_obriga_a_troca():
    sessao.iniciar_sessao(_usuario(senha_temporaria=True))
    assert sessao.precisa_trocar_senha() is True

    sessao.atualizar_usuario(_usuario(senha_temporaria=False))
    assert sessao.precisa_trocar_senha() is False


# ------------------------------------------------------------------- freio

def test_falhas_abaixo_do_limite_nao_bloqueiam():
    for _ in range(sessao.MAX_FALHAS - 1):
        sessao.registrar_falha(AGORA)

    assert sessao.espera_restante(AGORA) == 0


def test_falhas_acumulam_mesmo_consultando_a_espera_entre_elas():
    """Como a tela consulta a espera a cada rerun, ou seja, entre uma
    tentativa e a outra, essa consulta não pode apagar as falhas anteriores —
    o limite nunca seria alcançado. Foi assim que a primeira versão errou.
    """
    for _ in range(sessao.MAX_FALHAS):
        assert sessao.espera_restante(AGORA) == 0   # o que a tela faz antes do form
        sessao.registrar_falha(AGORA)

    assert sessao.espera_restante(AGORA) == sessao.ESPERA_SEGUNDOS


def test_limite_de_falhas_bloqueia_e_o_tempo_corre():
    for _ in range(sessao.MAX_FALHAS):
        sessao.registrar_falha(AGORA)

    assert sessao.espera_restante(AGORA) == sessao.ESPERA_SEGUNDOS
    assert sessao.espera_restante(AGORA + 30.5) == 30      # arredonda para cima


def test_passado_o_tempo_as_tentativas_voltam():
    """O bloqueio é um freio, não uma punição: depois da espera a pessoa tem
    o contador zerado, e não uma nova rodada de bloqueio a cada erro."""
    for _ in range(sessao.MAX_FALHAS):
        sessao.registrar_falha(AGORA)

    assert sessao.espera_restante(AGORA + sessao.ESPERA_SEGUNDOS) == 0

    sessao.registrar_falha(AGORA + sessao.ESPERA_SEGUNDOS)
    assert sessao.espera_restante(AGORA + sessao.ESPERA_SEGUNDOS) == 0


def test_login_certo_zera_o_contador():
    for _ in range(sessao.MAX_FALHAS - 1):
        sessao.registrar_falha(AGORA)
    sessao.iniciar_sessao(_usuario())

    # sem o reset, uma única falha depois do login já estouraria o limite
    sessao.registrar_falha(AGORA)
    assert sessao.espera_restante(AGORA) == 0


def test_encerrar_sessao_limpa_o_bloqueio():
    """Sair e entrar com outra conta na mesma aba não pode herdar o bloqueio
    de quem estava antes."""
    for _ in range(sessao.MAX_FALHAS):
        sessao.registrar_falha(AGORA)
    sessao.encerrar_sessao()

    assert sessao.espera_restante(AGORA) == 0


def test_restante_e_puro_e_tolera_ausencia_de_bloqueio():
    assert sessao._restante(None, AGORA) == 0
    assert sessao._restante(AGORA - 1, AGORA) == 0
    assert sessao._restante(AGORA + 0.2, AGORA) == 1
