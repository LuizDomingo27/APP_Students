"""Componentes visuais reutilizáveis da interface.

As funções que só transformam texto/número (resumir, formatar, contar
páginas) são puras de propósito — são elas que os testes unitários cobrem,
sem precisar subir o Streamlit.
"""
import html
from typing import Callable, Optional

import streamlit as st

from acervo.core.models import ResultadoBusca
from app import tema

MAX_LINHAS_PREVIA_CODIGO = 12


# ---------------------------------------------------------------- helpers puros

def resumir(texto: str, maximo: int = 240) -> str:
    """Uma linha só, cortada com reticências — para a prévia do card."""
    plano = " ".join(texto.split())
    if len(plano) <= maximo:
        return plano
    return plano[:maximo].rstrip() + "…"


def formatar_numero(n: int) -> str:
    """6595 -> '6.595' (padrão brasileiro)."""
    return f"{n:,}".replace(",", ".")


def total_de_paginas(total: int, limite: int) -> int:
    return (total + limite - 1) // limite if total > 0 else 0


def rotulo_categoria(nome: str, subcategoria: Optional[str]) -> str:
    return f"{nome} · {subcategoria}" if subcategoria else nome


def previa_de_codigo(codigo: str, max_linhas: int = MAX_LINHAS_PREVIA_CODIGO) -> str:
    linhas = codigo.strip().splitlines()
    if len(linhas) <= max_linhas:
        return "\n".join(linhas)
    return "\n".join(linhas[:max_linhas]) + "\n…"


def chip_html(texto: str, cor: str) -> str:
    return (
        f'<span class="acervo-chip" '
        f'style="color:{cor}; border-color:{cor}55; background:{cor}14">'
        f'{html.escape(texto)}</span>'
    )


def cartao_metrica_html(rotulo: str, valor: int, cor: str) -> str:
    return (
        f'<div class="acervo-metrica" style="--cor-metrica:{cor}">'
        f'<div class="valor">{formatar_numero(valor)}</div>'
        f'<div class="rotulo">{html.escape(rotulo)}</div>'
        f'</div>'
    )


# ------------------------------------------------------------ componentes com st

def card_resultado(
    resultado: ResultadoBusca,
    cores: dict,
    ao_abrir: Callable[[str], None],
) -> None:
    """Um resultado da busca: chip da categoria, título, prévia e ação de abrir."""
    cor = cores.get((resultado.categoria_nome, resultado.subcategoria), tema.ROXO)

    with st.container(key=f"card_{resultado.bloco_id}"):
        cabecalho = (
            '<div class="card-topo">'
            + chip_html(rotulo_categoria(resultado.categoria_nome, resultado.subcategoria), cor)
            + f'<span class="card-caminho">{html.escape(resultado.arquivo_caminho)}</span>'
            + "</div>"
        )
        if resultado.titulo:
            cabecalho += f'<div class="card-titulo">{html.escape(resultado.titulo)}</div>'
        if resultado.explicacao:
            cabecalho += (
                f'<div class="card-explicacao">{html.escape(resumir(resultado.explicacao))}</div>'
            )
        st.markdown(cabecalho, unsafe_allow_html=True)

        if resultado.codigo:
            st.code(previa_de_codigo(resultado.codigo), language=resultado.linguagem)

        col_meta, col_acao = st.columns([3.2, 1], vertical_alignment="center")
        meta = " · ".join(
            parte for parte in (
                resultado.linguagem,
                f"relevância {resultado.relevancia:.2f}",
            ) if parte
        )
        col_meta.markdown(f'<span class="card-meta">{html.escape(meta)}</span>', unsafe_allow_html=True)
        if col_acao.button(
            "Abrir arquivo",
            key=f"abrir_{resultado.bloco_id}",
            width="stretch",
        ):
            ao_abrir(resultado.arquivo_caminho)


def controles_de_paginacao(pagina_atual: int, paginas: int, chave_estado: str) -> None:
    """Anterior / página X de Y / Próxima — mexe no session_state via callbacks."""
    if paginas <= 1:
        return

    def _mudar(delta: int) -> None:
        novo = st.session_state.get(chave_estado, 1) + delta
        st.session_state[chave_estado] = min(max(novo, 1), paginas)

    _, col_ant, col_info, col_prox, _ = st.columns([2.2, 1, 1.4, 1, 2.2], vertical_alignment="center")
    col_ant.button(
        "← Anterior", key=f"{chave_estado}_ant", width="stretch",
        disabled=pagina_atual <= 1, on_click=_mudar, args=(-1,),
    )
    col_info.markdown(
        f'<div style="text-align:center" class="card-meta">página {pagina_atual} de {paginas}</div>',
        unsafe_allow_html=True,
    )
    col_prox.button(
        "Próxima →", key=f"{chave_estado}_prox", width="stretch",
        disabled=pagina_atual >= paginas, on_click=_mudar, args=(1,),
    )
