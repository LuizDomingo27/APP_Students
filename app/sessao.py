"""Quem está logado nesta aba, guardado no `session_state`.

A sessão vive **só em memória**: recarregar a página (F5) desloga, porque o
Streamlit descarta o `session_state` a cada conexão nova. Foi uma escolha —
manter login entre recargas exigiria um cookie assinado, e com ele viriam
segredo de assinatura, expiração e revogação para administrar.

Consequência que o resto do código precisa respeitar: o `Usuario` daqui é
uma **fotografia do momento do login** e não expira enquanto a aba estiver
aberta. Ele serve para saber o nome e desenhar (ou não) o menu de admin;
nunca para autorizar uma ação. Quem decide permissão é o banco, relido a
cada operação em `acervo.auth.admin_service`.
"""
import time
from math import ceil
from typing import Optional

import streamlit as st

from acervo.core.models import Usuario

_USUARIO = "sessao_usuario"
_FALHAS = "sessao_falhas_login"
_LIBERADO_EM = "sessao_liberado_em"

# Freio contra tentativa e erro no formulário. Não é defesa contra ataque
# automatizado — quem quisesse burlar bastaria abrir outra sessão, já que o
# contador vive nesta aba. O que segura força bruta de verdade é o custo do
# Argon2 (~40 ms por tentativa, ver `acervo.auth.senhas`); isto aqui é para
# a pessoa parar de chutar e ir procurar a senha certa.
MAX_FALHAS = 5
ESPERA_SEGUNDOS = 60


def usuario_atual() -> Optional[Usuario]:
    return st.session_state.get(_USUARIO)


def eh_admin() -> bool:
    usuario = usuario_atual()
    return bool(usuario and usuario.eh_admin)


def precisa_trocar_senha() -> bool:
    """True quando a senha em uso foi gerada por um admin.

    Enquanto for True o app não deve mostrar nenhuma outra página: a senha
    temporária passou por fora do sistema (foi lida em voz alta, colada em
    uma mensagem) e não pode virar a senha permanente de ninguém.
    """
    usuario = usuario_atual()
    return bool(usuario and usuario.senha_temporaria)


def iniciar_sessao(usuario: Usuario) -> None:
    st.session_state[_USUARIO] = usuario
    limpar_falhas()


def atualizar_usuario(usuario: Usuario) -> None:
    """Substitui a fotografia — usar após a própria pessoa trocar a senha."""
    st.session_state[_USUARIO] = usuario


def encerrar_sessao() -> None:
    st.session_state.pop(_USUARIO, None)
    limpar_falhas()


# ------------------------------------------------------------------- freio

def _restante(liberado_em: Optional[float], agora: float) -> int:
    """Segundos que faltam para o botão voltar. Função pura, testável direto."""
    if liberado_em is None:
        return 0
    return max(0, ceil(liberado_em - agora))


def espera_restante(agora: Optional[float] = None) -> int:
    """Quantos segundos ainda faltam até liberar o login. 0 = liberado.

    A tela chama esta função a cada rerun, ou seja, também entre uma tentativa
    e a seguinte — por isso ela só pode zerar o contador quando havia mesmo um
    bloqueio e ele venceu. Zerar sempre que não há bloqueio apagaria as falhas
    anteriores a cada tentativa, e o limite nunca seria alcançado.
    """
    liberado_em = st.session_state.get(_LIBERADO_EM)
    if liberado_em is None:
        return 0

    agora = time.monotonic() if agora is None else agora
    falta = _restante(liberado_em, agora)
    if falta == 0:
        # Cumprida a espera, a pessoa recomeça com as tentativas inteiras.
        limpar_falhas()
    return falta


def registrar_falha(agora: Optional[float] = None) -> None:
    agora = time.monotonic() if agora is None else agora
    falhas = st.session_state.get(_FALHAS, 0) + 1
    st.session_state[_FALHAS] = falhas
    if falhas >= MAX_FALHAS:
        st.session_state[_LIBERADO_EM] = agora + ESPERA_SEGUNDOS


def limpar_falhas() -> None:
    st.session_state[_FALHAS] = 0
    st.session_state.pop(_LIBERADO_EM, None)
