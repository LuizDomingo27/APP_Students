"""Fase 3 — interface web do Acervo DS.

Uso:
    streamlit run app/streamlit_app.py

Navbar própria (marca + navegação) e duas páginas: Busca e Dashboard.
Toda a lógica de dados vive em acervo.search.* — aqui é só apresentação.
"""
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import streamlit as st  # noqa: E402

from acervo.core.exceptions import AcervoError, ConfiguracaoError  # noqa: E402
from app.paginas import adicionar, busca, dashboard  # noqa: E402
from app.tema import aplicar_tema  # noqa: E402

st.set_page_config(
    page_title="Acervo DS",
    page_icon="🟣",
    layout="wide",
    initial_sidebar_state="collapsed",
)
aplicar_tema()


def main() -> None:
    with st.container(key="navbar"):
        col_marca, col_nav = st.columns([1.1, 1.3], vertical_alignment="center")
        col_marca.markdown(
            '<div class="marca"><span class="marca-ponto"></span>'
            'Acervo&nbsp;<span class="grad">DS</span></div>',
            unsafe_allow_html=True,
        )
        with col_nav:
            pagina = st.segmented_control(
                "Navegação", ["Busca", "Dashboard", "Adicionar"], default="Busca",
                key="nav_paginas", label_visibility="collapsed",
            ) or "Busca"

    try:
        if pagina == "Dashboard":
            dashboard.render()
        elif pagina == "Adicionar":
            adicionar.render()
        else:
            busca.render()
    except ConfiguracaoError as e:
        st.error(
            f"**Configuração incompleta.** {e}\n\n"
            "Crie o arquivo `.env` na raiz do projeto com o `DATABASE_URL` do Neon."
        )
    except AcervoError as e:
        st.error(f"Algo deu errado ao falar com o banco: {e}")


main()
