"""Página de busca — o coração do app.

Fluxo reativo: qualquer mudança em termo/modo/filtros reexecuta a busca
(barata: resultados ficam em cache por alguns minutos). Trocar os
parâmetros volta para a página 1; a paginação em si só muda o offset.
"""
import html

import streamlit as st

from acervo.core.exceptions import BuscaError
from acervo.search import busca_service
from acervo.search.estatisticas_service import resumo_do_acervo
from app import componentes as comp

_MODOS = {"Texto": "texto", "Código": "codigo"}
_RESULTADOS_POR_PAGINA = 10
_TODAS = "Todas"

_SUGESTOES = (
    ("regressão linear", "Texto"),
    ("groupby", "Código"),
    ("função de janela", "Texto"),
    ("LEFT JOIN", "Código"),
)


# ------------------------------------------------------------------ acesso a dados
# cache_data serializa os dataclasses (frozen) sem problema; TTL curto para
# refletir reindexações sem reiniciar o app.

@st.cache_data(ttl=600, show_spinner=False)
def _opcoes() -> dict:
    return busca_service.opcoes_de_filtro()


@st.cache_data(ttl=300, show_spinner=False)
def _buscar(termo, modo, categoria_id, linguagem, pagina):
    return busca_service.buscar(
        termo, modo=modo, categoria_id=categoria_id, linguagem=linguagem,
        pagina=pagina, limite=_RESULTADOS_POR_PAGINA,
    )


@st.cache_data(ttl=600, show_spinner=False)
def _conteudo(caminho: str):
    return busca_service.conteudo_do_arquivo(caminho)


@st.cache_data(ttl=600, show_spinner=False)
def _resumo():
    return resumo_do_acervo()


# ------------------------------------------------------------------ diálogo

@st.dialog("Arquivo completo", width="large")
def _abrir_arquivo(caminho: str) -> None:
    st.markdown(f'<span class="card-caminho">{html.escape(caminho)}</span>', unsafe_allow_html=True)
    try:
        blocos = _conteudo(caminho)
    except BuscaError as e:
        st.error(str(e))
        return

    for bloco in blocos:
        if bloco.titulo:
            st.markdown(f"#### {bloco.titulo}")
        if bloco.explicacao:
            st.markdown(bloco.explicacao)
        if bloco.codigo:
            st.code(bloco.codigo, language=bloco.linguagem)
        st.divider()


# ------------------------------------------------------------------ página

def _sugerir(termo: str, modo: str) -> None:
    st.session_state["termo_busca"] = termo
    st.session_state["modo_busca"] = modo


def _hero() -> None:
    try:
        resumo = _resumo()
        subtitulo = (
            f"<span class='destaque'>{comp.formatar_numero(resumo.total_blocos)}</span> blocos "
            f"de estudo extraídos de {comp.formatar_numero(resumo.total_arquivos)} arquivos — "
            f"notebooks, scripts SQL, slides e PDFs do MBA."
        )
    except BuscaError:
        subtitulo = "Notebooks, scripts SQL, slides e PDFs do MBA, pesquisáveis num lugar só."

    st.markdown(
        "<div class='hero'>"
        "<h1>Todo o seu material de <span class='grad'>Data Science</span>, pesquisável.</h1>"
        f"<p>{subtitulo}</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.write("")
    _, *cols, _ = st.columns([1.2] + [1] * len(_SUGESTOES) + [1.2])
    for col, (termo, modo) in zip(cols, _SUGESTOES):
        col.button(termo, key=f"sugestao_{termo}", width="stretch",
                   on_click=_sugerir, args=(termo, modo))


def render() -> None:
    try:
        opcoes = _opcoes()
    except BuscaError as e:
        st.error(str(e))
        return

    cores = {(c.nome, c.subcategoria): c.cor for c in opcoes["categorias"]}
    rotulos_categoria = {
        comp.rotulo_categoria(c.nome, c.subcategoria): c.id for c in opcoes["categorias"]
    }

    termo = st.text_input(
        "O que você procura?", key="termo_busca",
        placeholder="Busque um conceito (regressão, janela…) ou um trecho de código (df.groupby, LEFT JOIN…)",
        label_visibility="collapsed",
    )

    # o estado inicial vem daqui (e não de default=) porque as sugestões do
    # hero também escrevem em modo_busca via session_state
    st.session_state.setdefault("modo_busca", "Texto")
    col_modo, col_cat, col_lang, _ = st.columns([1.35, 1.5, 1.1, 1.6], vertical_alignment="center")
    modo_rotulo = col_modo.segmented_control(
        "Modo", list(_MODOS), key="modo_busca",
        label_visibility="collapsed",
    ) or "Texto"
    categoria_rotulo = col_cat.selectbox(
        "Categoria", [_TODAS, *rotulos_categoria], key="filtro_categoria",
        label_visibility="collapsed",
    )
    linguagem_rotulo = col_lang.selectbox(
        "Linguagem", [_TODAS, *opcoes["linguagens"]], key="filtro_linguagem",
        label_visibility="collapsed",
    )

    if not termo.strip():
        _hero()
        return

    categoria_id = rotulos_categoria.get(categoria_rotulo)
    linguagem = None if linguagem_rotulo == _TODAS else linguagem_rotulo
    modo = _MODOS[modo_rotulo]

    # novos parâmetros => volta para a página 1
    chave = (termo, modo, categoria_id, linguagem)
    if st.session_state.get("chave_busca") != chave:
        st.session_state["chave_busca"] = chave
        st.session_state["pagina_busca"] = 1
    pagina_atual = st.session_state.setdefault("pagina_busca", 1)

    try:
        with st.spinner("Buscando no acervo…"):
            pagina = _buscar(termo, modo, categoria_id, linguagem, pagina_atual)
    except BuscaError as e:
        st.error(str(e))
        return

    st.write("")
    if pagina.total == 0:
        dica = (
            "Tente o modo **Código** para trechos literais como `df.groupby`."
            if modo == "texto"
            else "Tente o modo **Texto** para conceitos e explicações."
        )
        st.info(f"Nenhum resultado para **{termo}**. {dica}")
        return

    st.markdown(
        f'<span class="card-meta">{comp.formatar_numero(pagina.total)} resultado(s)</span>',
        unsafe_allow_html=True,
    )
    for resultado in pagina.resultados:
        comp.card_resultado(resultado, cores, ao_abrir=_abrir_arquivo)

    comp.controles_de_paginacao(
        pagina_atual,
        comp.total_de_paginas(pagina.total, _RESULTADOS_POR_PAGINA),
        chave_estado="pagina_busca",
    )
