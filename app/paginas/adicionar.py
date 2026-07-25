"""Página "Adicionar" — sobe novos conteúdos para o acervo pela interface.

O arquivo enviado é parseado na hora e gravado direto no banco (origem
'upload'); ele não precisa existir nas pastas do disco e não é afetado pela
limpeza de órfãos. Depois de qualquer gravação, o cache das outras páginas
é limpo para o conteúdo novo aparecer imediatamente na busca e no dashboard.
"""
import streamlit as st

from acervo.core.exceptions import BuscaError, UploadError
from acervo.search import busca_service, upload_service
from app import componentes as comp

_ICONES_STATUS = {
    "adicionado": "✅",
    "atualizado": "🔄",
    "sem_alteracao": "⏭️",
    "duplicado": "⚠️",
}


@st.cache_data(ttl=600, show_spinner=False)
def _opcoes() -> dict:
    return busca_service.opcoes_de_filtro()


def _mensagem(nome: str, resultado) -> tuple[str, str]:
    """(nível, texto) para exibir o resultado de um upload."""
    icone = _ICONES_STATUS.get(resultado.status, "•")
    if resultado.status == "adicionado":
        return "success", f"{icone} **{nome}** adicionado — {resultado.total_blocos} bloco(s) extraído(s)."
    if resultado.status == "atualizado":
        return "success", f"{icone} **{nome}** atualizado — {resultado.total_blocos} bloco(s) extraído(s)."
    if resultado.status == "sem_alteracao":
        return "info", f"{icone} **{nome}** já estava no acervo, sem alterações."
    return "warning", f"{icone} **{nome}** é idêntico a `{resultado.duplicado_de}` — não foi duplicado."


def _form_nova_categoria() -> None:
    with st.expander("Criar nova categoria"):
        with st.form("form_nova_categoria", clear_on_submit=True, border=False):
            col_nome, col_sub, col_cor = st.columns([2, 2, 1], vertical_alignment="bottom")
            nome = col_nome.text_input("Nome", placeholder="ex.: Machine Learning")
            subcategoria = col_sub.text_input("Subcategoria (opcional)", placeholder="ex.: Módulo 1")
            cor = col_cor.color_picker("Cor", value="#a78bfa")
            if st.form_submit_button("Criar categoria"):
                try:
                    categoria = upload_service.criar_categoria(nome, subcategoria, cor)
                except UploadError as e:
                    st.error(str(e))
                else:
                    _opcoes.clear()
                    st.success(
                        f"Categoria **{comp.rotulo_categoria(categoria.nome, categoria.subcategoria)}** "
                        "criada — já disponível na lista acima."
                    )


def render() -> None:
    st.markdown("### Adicionar conteúdo ao acervo")
    st.caption(
        "Envie notebooks, scripts, PDFs ou slides: o conteúdo é extraído e gravado "
        "direto no banco — o arquivo não precisa ficar nas pastas do projeto."
    )
    st.write("")

    try:
        opcoes = _opcoes()
    except BuscaError as e:
        st.error(str(e))
        return

    categorias = opcoes["categorias"]
    if not categorias:
        st.info("Nenhuma categoria ainda — crie a primeira abaixo.")
    rotulos = {comp.rotulo_categoria(c.nome, c.subcategoria): c for c in categorias}

    categoria_rotulo = st.selectbox("Categoria do conteúdo", list(rotulos))
    _form_nova_categoria()

    st.write("")
    arquivos = st.file_uploader(
        "Arquivos",
        type=upload_service.extensoes_aceitas(),
        accept_multiple_files=True,
        help="Formatos aceitos: " + ", ".join(f".{e}" for e in upload_service.extensoes_aceitas()),
    )

    if not st.button("Adicionar ao acervo", type="primary", disabled=not (arquivos and rotulos)):
        return

    categoria = rotulos[categoria_rotulo]
    gravou_algo = False
    with st.spinner("Processando e gravando no banco…"):
        for enviado in arquivos:
            try:
                resultado = upload_service.adicionar_conteudo(
                    enviado.name, enviado.getvalue(), categoria,
                )
            except UploadError as e:
                st.error(f"❌ **{enviado.name}**: {e}")
                continue

            nivel, texto = _mensagem(enviado.name, resultado)
            getattr(st, nivel)(texto)
            if resultado.status in ("adicionado", "atualizado"):
                gravou_algo = True

    if gravou_algo:
        # invalida os caches das páginas de busca/dashboard para refletir agora
        st.cache_data.clear()
        st.toast("Acervo atualizado — o conteúdo novo já aparece na busca.", icon="🟣")
