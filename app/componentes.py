"""Componentes visuais reutilizáveis da interface.

As funções que só transformam texto/número (resumir, formatar, contar
páginas) são puras de propósito — são elas que os testes unitários cobrem,
sem precisar subir o Streamlit.
"""
import html
from datetime import datetime
from typing import Callable, Optional, Sequence

import streamlit as st

from acervo.core.models import Bloco, ConteudoCategoria, ResultadoBusca
from app import tema

MAX_LINHAS_PREVIA_CODIGO = 12

PAGINAS_ABERTAS = ("Busca", "Dashboard", "Adicionar")
PAGINA_ADMIN = "Usuários"

# Os rótulos "sem filtro" dos dropdowns da busca. Ficam aqui porque não são só
# da página de busca: o assistente de voz (`app.voz`) precisa escrever
# exatamente estes valores no `session_state` para limpar um filtro — um
# selectbox recusa qualquer valor que não esteja entre suas opções.
FILTRO_TODAS = "Todas"
FILTRO_TODO_CONTEUDO = "Todo o conteúdo"


# ---------------------------------------------------------------- helpers puros

def opcoes_de_navegacao(eh_admin: bool) -> list[str]:
    """Os itens que a navbar mostra para quem está logado.

    Esconder "Usuários" de quem não é admin é conveniência visual, não
    segurança: a sessão é uma fotografia do login (ver `app.sessao`) e pode
    estar velha. Quem barra a ação de fato é `acervo.auth.admin_service`,
    que relê o papel no banco a cada operação.
    """
    if eh_admin:
        return [*PAGINAS_ABERTAS, PAGINA_ADMIN]
    return list(PAGINAS_ABERTAS)


def primeiro_nome(nome: str) -> str:
    """'Ana Silva Souza' -> 'Ana' — o botão da conta na navbar é estreito."""
    partes = nome.split()
    return partes[0] if partes else nome


def formatar_data(quando: Optional[datetime]) -> str:
    """Data curta no padrão brasileiro; '—' quando nunca aconteceu."""
    return quando.strftime("%d/%m/%Y") if quando else "—"

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


def rotulo_conteudo(caminho: str, pasta_raiz: Optional[str] = None, *, niveis: int = 1) -> str:
    """Nome legível de um arquivo dentro da categoria.

    A pasta raiz sai do rótulo porque ela *é* a categoria já escolhida no
    dropdown anterior. `niveis` diz quantos segmentos finais do caminho entram
    no rótulo (0 = o caminho relativo inteiro); o que foi cortado vira "…/",
    para o nome do arquivo caber na largura do filtro.
    """
    partes = [parte for parte in caminho.replace("\\", "/").split("/") if parte]
    if pasta_raiz and partes and partes[0] == pasta_raiz:
        partes = partes[1:]
    if not partes:
        return caminho
    if niveis <= 0 or niveis >= len(partes):
        return "/".join(partes)
    return "…/" + "/".join(partes[-niveis:])


def rotulos_de_conteudo(conteudos: Sequence[ConteudoCategoria]) -> dict[str, str]:
    """Rótulo exibido → caminho do arquivo, na ordem em que vieram do banco.

    Só o nome do arquivo já basta na maioria das categorias; quando ele se
    repete (o acervo tem vários "querys_da_aula.txt"), o rótulo ganha uma
    pasta de cada vez até todos ficarem distintos. A unicidade não é cosmética:
    rótulos iguais viram a mesma chave do dicionário e um dos arquivos sumiria
    do dropdown.
    """
    itens = list(conteudos)
    bases = [c.caminho for c in itens]  # último recurso — único por construção
    for niveis in (1, 2, 0):
        candidatos = [rotulo_conteudo(c.caminho, c.pasta_raiz, niveis=niveis) for c in itens]
        if len(set(candidatos)) == len(itens):
            bases = candidatos
            break

    rotulos: dict[str, str] = {}
    for conteudo, base in zip(itens, bases):
        plural = "s" if conteudo.total_blocos != 1 else ""
        rotulos[f"{base} · {conteudo.total_blocos} bloco{plural}"] = conteudo.caminho
    return rotulos


def _primeira_linha_util(texto: Optional[str]) -> str:
    """A primeira linha que diz alguma coisa.

    Células de notebook começam com faixas de '#' e '=' como separador visual;
    num sumário elas ocupariam a linha inteira sem informar nada.
    """
    for linha in (texto or "").splitlines():
        limpo = linha.strip().strip("#").strip(" #-=*_").strip()
        if any(caractere.isalnum() for caractere in limpo):
            return limpo
    return ""


def titulo_do_bloco(bloco: Bloco) -> str:
    """O melhor rótulo curto para um bloco — nem todo parser produz título."""
    if bloco.titulo and bloco.titulo.strip():
        return bloco.titulo.strip()
    for alternativa in (bloco.explicacao, bloco.codigo):
        linha = _primeira_linha_util(alternativa)
        if linha:
            return resumir(linha, 90)
    return "(bloco sem título)"


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
