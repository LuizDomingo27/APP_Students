"""Dashboard — visão geral do acervo: totais e distribuição por categoria."""
import altair as alt
import pandas as pd
import streamlit as st

from acervo.core.exceptions import BuscaError
from acervo.search.estatisticas_service import resumo_do_acervo
from app import componentes as comp
from app import tema


@st.cache_data(ttl=600, show_spinner=False)
def _resumo():
    return resumo_do_acervo()


def _grafico_por_categoria(df: pd.DataFrame) -> alt.Chart:
    eixo_texto = dict(labelColor=tema.TEXTO_SUAVE, titleColor=tema.TEXTO_SUAVE)
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopRight=7, cornerRadiusBottomRight=7)
        .encode(
            y=alt.Y("categoria:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=220, **eixo_texto)),
            x=alt.X("blocos:Q", title="blocos indexados",
                    axis=alt.Axis(gridColor=tema.GRADE_GRAFICO, domainOpacity=0, **eixo_texto)),
            color=alt.Color("categoria:N", legend=None,
                            scale=alt.Scale(domain=list(df["categoria"]), range=list(df["cor"]))),
            tooltip=[
                alt.Tooltip("categoria:N", title="Categoria"),
                alt.Tooltip("arquivos:Q", title="Arquivos"),
                alt.Tooltip("blocos:Q", title="Blocos"),
            ],
        )
        .properties(height=max(240, 42 * len(df)), background="transparent")
        .configure_view(strokeOpacity=0)
    )


def render() -> None:
    try:
        resumo = _resumo()
    except BuscaError as e:
        st.error(str(e))
        return

    st.markdown("### Visão geral do acervo")
    st.write("")

    metricas = (
        ("Arquivos indexados", resumo.total_arquivos, tema.ROXO),
        ("Blocos de conteúdo", resumo.total_blocos, tema.CIANO),
        ("Categorias", len(resumo.por_categoria), tema.VERDE),
        ("Falhas de leitura", resumo.total_falhas, tema.ROSA),
    )
    for col, (rotulo, valor, cor) in zip(st.columns(len(metricas)), metricas):
        col.markdown(comp.cartao_metrica_html(rotulo, valor, cor), unsafe_allow_html=True)

    st.write("")
    st.write("")
    st.markdown("##### Blocos por categoria")

    df = pd.DataFrame(
        {
            "categoria": comp.rotulo_categoria(e.categoria_nome, e.subcategoria),
            "arquivos": e.total_arquivos,
            "blocos": e.total_blocos,
            "cor": e.cor,
        }
        for e in resumo.por_categoria
    ).sort_values("blocos", ascending=False)

    st.altair_chart(_grafico_por_categoria(df), width="stretch")

    st.markdown("##### Detalhe por categoria")
    st.dataframe(
        df.rename(columns={"categoria": "Categoria", "arquivos": "Arquivos", "blocos": "Blocos"})
          .drop(columns="cor"),
        hide_index=True,
        width="stretch",
    )

    if resumo.total_falhas:
        st.caption(
            f"⚠ {comp.formatar_numero(resumo.total_falhas)} arquivo(s) não puderam ser lidos "
            "durante a indexação (detalhes na tabela falhas_indexacao do banco)."
        )
