"""Fase 3/4 — interface web do Acervo DS.

Uso:
    streamlit run app/streamlit_app.py

Este arquivo é o porteiro: decide *qual* tela aparece. São três estados, e
eles são exclusivos — quem cai num não vê nada dos outros:

    sem sessão              -> login
    senha temporária        -> troca de senha obrigatória
    logado                  -> navbar + páginas

O segundo estado existe porque a senha gerada por um admin circulou por fora
do sistema (foi ditada, colada numa mensagem); enquanto ela valer, a pessoa
não navega. Toda a lógica de dados vive em acervo.* — aqui é só apresentação.
"""
import html
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import streamlit as st  # noqa: E402

from acervo.core.exceptions import AcervoError, ConfiguracaoError  # noqa: E402
from acervo.core.models import Usuario  # noqa: E402
from app import componentes, sessao, voz  # noqa: E402
from app.paginas import (  # noqa: E402
    adicionar, busca, dashboard, login, trocar_senha, usuarios,
)
from app.tema import aplicar_tema  # noqa: E402

st.set_page_config(
    page_title="My brain - my friend",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

aplicar_tema()

# A troca de senha voluntária não é um item da navbar: entra pelo menu da
# conta e sai sozinha assim que a pessoa clica em qualquer página.
_CONTA = "mostrar_conta"


def _fechar_conta() -> None:
    st.session_state[_CONTA] = False


def _menu_da_conta(usuario: Usuario) -> None:
    with st.popover(componentes.primeiro_nome(usuario.nome), width="stretch"):
        # HTML em vez de st.caption porque o Markdown do Streamlit transforma
        # e-mail em link `mailto:` — aqui ele é só identificação da conta.
        st.markdown(
            f'<p class="conta-email">{html.escape(usuario.email)}</p>',
            unsafe_allow_html=True,
        )
        if st.button("Trocar senha", key="btn_trocar_senha", width="stretch"):
            st.session_state[_CONTA] = True
            st.rerun()
        if st.button("Sair", key="btn_sair", width="stretch"):
            sessao.encerrar_sessao()
            st.rerun()


def _navbar(usuario: Usuario) -> str:
    """Desenha a barra do topo e devolve a página escolhida."""
    with st.container(key="navbar"):
        col_marca, col_nav, col_conta = st.columns(
            [1.0, 1.5, 0.5], vertical_alignment="center",
        )
        
        col_marca.markdown(
            '<div class="marca"><span class="marca-ponto"></span>'
            'My Brain&nbsp;<span class="grad">My Friend</span></div>',
            unsafe_allow_html=True,
        )
        
        with col_nav:
            # a página inicial é semeada no estado em vez de vir por `default=`:
            # o assistente de voz também escreve nesta chave, e o Streamlit
            # reclama quando um widget tem default *e* valor no session_state
            st.session_state.setdefault("nav_paginas", "Busca")
            pagina = st.segmented_control(
                "Navegação",
                componentes.opcoes_de_navegacao(sessao.eh_admin()),
                key="nav_paginas",
                label_visibility="collapsed",
                on_change=_fechar_conta,
            ) or "Busca"
        with col_conta:
            _menu_da_conta(usuario)

    return pagina


def _pagina(nome: str) -> None:
    if st.session_state.get(_CONTA):
        trocar_senha.render()
    elif nome == "Dashboard":
        dashboard.render()
    elif nome == "Adicionar":
        adicionar.render()
    elif nome == componentes.PAGINA_ADMIN:
        usuarios.render()
    else:
        busca.render()


def main() -> None:
    usuario = sessao.usuario_atual()
    if usuario is None:
        login.render()
        return

    if sessao.precisa_trocar_senha():
        trocar_senha.render(obrigatoria=True)
        return

    # Antes da navbar e das páginas, sem exceção: o assistente age escrevendo
    # nas chaves dos widgets, e um widget já instanciado ignora a escrita até
    # o próximo run. Ver a nota de ordem no topo de `app.voz`.
    voz.processar_pendente(eh_admin=sessao.eh_admin())

    pagina = _navbar(usuario)
    voz.painel()

    try:
        _pagina(pagina)
    except ConfiguracaoError as e:
        st.error(
            f"**Configuração incompleta.** {e}\n\n"
            "Crie o arquivo `.env` na raiz do projeto com o `DATABASE_URL` do Neon."
        )
    except AcervoError as e:
        st.error(f"Algo deu errado ao falar com o banco: {e}")

main()
