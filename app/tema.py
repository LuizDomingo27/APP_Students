"""Tema visual do Acervo DS — dark moderno com neon suave.

Tudo que é *cor e forma* mora aqui: a paleta exportada (usada também nos
gráficos do dashboard) e o CSS injetado uma vez por página. O restante do
app não conhece hex de cor nenhum — se o visual mudar, muda num lugar só.
"""
import streamlit as st

# Paleta — neon suavizado sobre fundo quase-preto arroxeado
FUNDO = "#0e0b16"
FUNDO_CARD = "#151021"
ROXO = "#a78bfa"
ROXO_PROFUNDO = "#7c3aed"
ROXO_DARK = "#5b21b6"
BORDA_INPUT = "rgba(109, 40, 217, 0.55)"
CIANO = "#7dd3fc"
ROSA = "#f0a6ce"
VERDE = "#6ee7b7"
AMBAR = "#fcd34d"
TEXTO = "#e9e4f7"
TEXTO_SUAVE = "#9a93b8"
BORDA = "rgba(167, 139, 250, 0.26)"
GRADE_GRAFICO = "rgba(233, 228, 247, 0.07)"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] * {{
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
}}
code, pre, [data-testid="stCode"] * {{
    font-family: 'JetBrains Mono', 'Cascadia Code', monospace !important;
}}
/* os ícones do Streamlit são ligaduras da fonte Material Symbols — sem ela
   voltam a ser texto ("arrow_right"); o override global de Inter acima não
   pode alcançá-los */
[data-testid="stIconMaterial"], span[class*="material-symbols"] {{
    font-family: 'Material Symbols Rounded' !important;
}}

/* esconde o chrome padrão do Streamlit — o app tem navbar própria */
[data-testid="stHeader"], [data-testid="stToolbar"] {{ display: none; }}
.block-container {{ padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1150px; }}

/* ---------- navbar ---------- */
div[class*="st-key-navbar"] {{
    position: sticky; top: 0; z-index: 99;
    background: rgba(14, 11, 22, 0.86);
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border: 1px solid {BORDA};
    border-radius: 14px;
    padding: 0.55rem 1.2rem;
    margin-bottom: 1.6rem;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
}}
.marca {{
    font-size: 1.25rem; font-weight: 800; letter-spacing: 0.01em;
    color: {TEXTO}; display: flex; align-items: center; gap: 0.55rem;
}}
.marca-ponto {{
    width: 11px; height: 11px; border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, {CIANO}, {ROXO_PROFUNDO});
    box-shadow: 0 0 12px {ROXO_PROFUNDO}aa;
}}
.grad {{
    background: linear-gradient(92deg, {ROXO} 10%, {CIANO} 90%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}}
div[class*="st-key-nav_paginas"] {{ display: flex; justify-content: flex-end; }}

/* menu da conta — encostado na direita, discreto ao lado da navegação */
div[class*="st-key-navbar"] [data-testid="stPopover"] {{ display: flex; justify-content: flex-end; }}
div[class*="st-key-navbar"] [data-testid="stPopover"] button {{
    background: rgba(167, 139, 250, 0.10);
    border: 1px solid {BORDA};
    color: {TEXTO};
}}
div[class*="st-key-navbar"] [data-testid="stPopover"] button:hover:enabled {{
    background: rgba(167, 139, 250, 0.18);
    border-color: rgba(167, 139, 250, 0.5);
    box-shadow: none;
    color: {TEXTO};
    filter: none;
}}
/* o painel do popover é renderizado fora da navbar, no fim do body */
[data-testid="stPopoverBody"] {{ min-width: 210px; }}
.conta-email {{
    color: {TEXTO_SUAVE}; font-size: 0.8rem;
    margin: 0 0 0.7rem 0; overflow-wrap: anywhere;
}}

/* ---------- cartão de acesso (login, cadastro, troca de senha) ---------- */
div[class*="st-key-cartao_acesso"] {{
    background: linear-gradient(180deg, {FUNDO_CARD} 0%, #120e1d 100%);
    border: 1px solid {BORDA};
    border-radius: 16px;
    padding: 1.8rem 1.9rem 1.4rem;
    margin-top: 3.2rem;
    box-shadow: 0 12px 44px rgba(0, 0, 0, 0.4);
}}
.acesso-cabecalho {{ text-align: center; margin-bottom: 1.4rem; }}
.acesso-cabecalho .marca {{ justify-content: center; font-size: 1.5rem; }}
.acesso-cabecalho p {{ color: {TEXTO_SUAVE}; font-size: 0.9rem; margin: 0.45rem 0 0 0; }}

/* ---------- hero (estado inicial da busca) ---------- */
.hero {{ text-align: center; padding: 2.4rem 0 0.8rem 0; }}
.hero h1 {{
    font-size: 2.3rem; font-weight: 800; line-height: 1.25;
    color: {TEXTO}; margin-bottom: 0.7rem;
}}
.hero p {{ color: {TEXTO_SUAVE}; font-size: 1.02rem; max-width: 620px; margin: 0 auto; }}
.hero .destaque {{ color: {CIANO}; font-weight: 600; }}

/* ---------- cards de resultado ---------- */
div[class*="st-key-card_"] {{
    background: linear-gradient(180deg, {FUNDO_CARD} 0%, #120e1d 100%);
    border: 1px solid {BORDA};
    border-radius: 14px;
    padding: 1.05rem 1.25rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}}
div[class*="st-key-card_"]:hover {{
    border-color: rgba(167, 139, 250, 0.55);
    box-shadow: 0 0 26px rgba(124, 58, 237, 0.16);
    transform: translateY(-1px);
}}
.card-topo {{ display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap; margin-bottom: 0.45rem; }}
.card-caminho {{
    color: {TEXTO_SUAVE}; font-size: 0.78rem;
    font-family: 'JetBrains Mono', monospace !important;
    overflow-wrap: anywhere;
}}
.card-titulo {{ font-size: 1.08rem; font-weight: 700; color: {TEXTO}; margin-bottom: 0.25rem; }}
.card-explicacao {{ color: {TEXTO_SUAVE}; font-size: 0.92rem; line-height: 1.55; margin-bottom: 0.35rem; }}
.card-meta {{ color: {TEXTO_SUAVE}; font-size: 0.78rem; letter-spacing: 0.02em; }}

/* ---------- sumário do conteúdo escolhido (busca sem termo) ---------- */
.sumario {{
    list-style: none; padding: 0.9rem 1.2rem; margin: 0.7rem 0;
    background: linear-gradient(180deg, {FUNDO_CARD} 0%, #120e1d 100%);
    border: 1px solid {BORDA}; border-radius: 14px;
}}
.sumario li {{
    color: {TEXTO}; font-size: 0.92rem; line-height: 1.5;
    padding: 0.32rem 0 0.32rem 1.05rem; position: relative;
    border-bottom: 1px solid rgba(167, 139, 250, 0.10);
}}
.sumario li:last-child {{ border-bottom: none; }}
.sumario li::before {{ content: "▸"; position: absolute; left: 0; color: {ROXO}; }}

.acervo-chip {{
    display: inline-block; padding: 0.14rem 0.65rem;
    border: 1px solid; border-radius: 999px;
    font-size: 0.74rem; font-weight: 600; letter-spacing: 0.03em;
    white-space: nowrap;
}}

/* ---------- cartões de métrica (dashboard) ---------- */
.acervo-metrica {{
    background: linear-gradient(180deg, {FUNDO_CARD} 0%, #120e1d 100%);
    border: 1px solid {BORDA};
    border-top: 2px solid var(--cor-metrica, {ROXO});
    border-radius: 14px;
    padding: 1.05rem 1.2rem;
    box-shadow: 0 0 0 rgba(0, 0, 0, 0);
    transition: box-shadow 0.2s ease;
}}
.acervo-metrica:hover {{ box-shadow: 0 0 22px color-mix(in srgb, var(--cor-metrica) 18%, transparent); }}
.acervo-metrica .valor {{ font-size: 1.9rem; font-weight: 800; color: {TEXTO}; line-height: 1.1; }}
.acervo-metrica .rotulo {{
    color: {TEXTO_SUAVE}; font-size: 0.8rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.3rem;
}}

/* ---------- inputs — borda roxa suave escura ---------- */
[data-testid="stTextInput"] input {{ padding: 0.85rem 1rem; font-size: 1.02rem; }}
[data-testid="stTextInput"] div[data-baseweb="input"],
[data-testid="stTextArea"] div[data-baseweb="textarea"],
[data-testid="stNumberInput"] div[data-baseweb="input"],
[data-testid="stDateInput"] div[data-baseweb="input"],
[data-testid="stTimeInput"] div[data-baseweb="input"],
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
    border: 1px solid {BORDA_INPUT};
    background-color: {FUNDO_CARD};
}}
[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stTextArea"] div[data-baseweb="textarea"]:focus-within,
[data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stDateInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stTimeInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:focus-within {{
    border-color: {ROXO_PROFUNDO};
    box-shadow: 0 0 0 1px {ROXO_PROFUNDO}55, 0 0 20px {ROXO_PROFUNDO}30;
}}
[data-testid="stFileUploaderDropzone"] {{
    border: 1px dashed {BORDA_INPUT};
    background-color: {FUNDO_CARD};
}}

/* ---------- botões — roxo dark ---------- */
.stButton button, .stDownloadButton button, .stFormSubmitButton button,
[data-testid="stFileUploader"] button {{
    background: linear-gradient(180deg, {ROXO_PROFUNDO} 0%, {ROXO_DARK} 100%);
    border: 1px solid {ROXO_PROFUNDO};
    color: #f5f1ff;
    font-weight: 600;
    transition: filter 0.15s ease, border-color 0.15s ease,
                box-shadow 0.15s ease, transform 0.1s ease;
}}
.stButton button:hover:enabled, .stDownloadButton button:hover:enabled,
.stFormSubmitButton button:hover:enabled,
[data-testid="stFileUploader"] button:hover:enabled {{
    filter: brightness(1.12);
    border-color: {ROXO};
    box-shadow: 0 0 16px rgba(124, 58, 237, 0.35);
    color: #f5f1ff;
}}
.stButton button:active:enabled, .stDownloadButton button:active:enabled,
.stFormSubmitButton button:active:enabled {{ transform: translateY(1px); }}

/* No painel de usuários, tudo roxo faria "Recusar" e "Bloquear" terem o mesmo
   peso visual de "Aprovar" — e um clique errado ali tira o acesso de alguém.
   As ações que retiram acesso ficam contornadas, discretas. */
div[class*="st-key-card_usuario_"] .stButton button[kind="secondary"] {{
    background: transparent;
    border: 1px solid {BORDA_INPUT};
    color: {TEXTO_SUAVE};
}}
div[class*="st-key-card_usuario_"] .stButton button[kind="secondary"]:hover:enabled {{
    background: rgba(167, 139, 250, 0.10);
    border-color: {ROXO};
    box-shadow: none;
    color: {TEXTO};
    filter: none;
}}

/* segmented control (navegação) segue o mesmo roxo */
button[kind="segmented_control"] {{ border-color: {BORDA_INPUT}; }}
button[kind="segmented_controlActive"] {{
    background: linear-gradient(180deg, {ROXO_PROFUNDO} 0%, {ROXO_DARK} 100%) !important;
    border-color: {ROXO_PROFUNDO} !important;
    color: #f5f1ff !important;
}}

[data-testid="stCode"] {{ border: 1px solid {BORDA_INPUT}; border-radius: 10px; }}

/* ---------- assistente de voz ---------- */
/* O botão do microfone é criado por JS na página principal (ver `app.voz`) e
   encaixado no slot que o Streamlit desenha — por isso ele é estilizado aqui
   por classe, e não pelo seletor de .stButton. */
div[class*="st-key-voz_painel"] {{
    background: rgba(21, 16, 33, 0.55);
    border: 1px solid {BORDA};
    border-radius: 14px;
    padding: 0.55rem 0.85rem;
    margin-bottom: 0.9rem;
}}
/* o iframe da ponte é só instalador de script — não ocupa espaço na tela */
div[class*="st-key-voz_painel"] iframe {{ display: none; }}

.voz-slot {{ display: flex; align-items: center; gap: 0.5rem; min-height: 38px; }}

.voz-botao {{
    background: linear-gradient(180deg, {ROXO_PROFUNDO} 0%, {ROXO_DARK} 100%);
    border: 1px solid {ROXO_PROFUNDO};
    border-radius: 9px;
    color: #f5f1ff;
    cursor: pointer;
    font-family: 'Inter', sans-serif;
    font-size: 0.86rem;
    font-weight: 600;
    padding: 0.42rem 0.85rem;
    transition: filter 0.15s ease, box-shadow 0.15s ease;
    white-space: nowrap;
}}
.voz-botao:hover:enabled {{ filter: brightness(1.12); box-shadow: 0 0 16px rgba(124, 58, 237, 0.35); }}
.voz-botao:disabled {{ background: transparent; border-color: {BORDA}; color: {TEXTO_SUAVE}; cursor: not-allowed; }}

/* enquanto ouve, o botão pulsa: é o único aviso de que o microfone está
   aberto para quem não olha a barra de status do navegador */
.voz-botao.ouvindo {{
    background: linear-gradient(180deg, #b91c5c 0%, #831843 100%);
    border-color: {ROSA};
    animation: voz-pulso 1.5s ease-in-out infinite;
}}
@keyframes voz-pulso {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(240, 166, 206, 0.45); }}
    50%      {{ box-shadow: 0 0 0 7px rgba(240, 166, 206, 0); }}
}}

.voz-status {{ color: {TEXTO_SUAVE}; font-size: 0.72rem; line-height: 1.1; }}

.voz-badge {{
    border-radius: 8px;
    font-size: 0.78rem;
    margin-top: 0.5rem;
    padding: 0.34rem 0.7rem;
}}
.voz-badge.voz-ok {{ background: rgba(110, 231, 183, 0.10); border: 1px solid {VERDE}55; color: {VERDE}; }}
.voz-badge.voz-aviso {{ background: rgba(252, 211, 77, 0.10); border: 1px solid {AMBAR}55; color: {AMBAR}; }}
.voz-badge.voz-erro {{ background: rgba(240, 166, 206, 0.10); border: 1px solid {ROSA}55; color: {ROSA}; }}

.voz-exemplo {{
    color: {TEXTO_SUAVE};
    font-size: 0.78rem;
    padding: 0.12rem 0 0.12rem 0.6rem;
    border-left: 2px solid {BORDA};
    margin-bottom: 0.15rem;
}}

/* ---------- diálogo (arquivo completo) ---------- */
div[role="dialog"] {{
    background: #14101f;
    border: 1px solid rgba(167, 139, 250, 0.35);
    border-radius: 16px;
    box-shadow: 0 0 40px rgba(124, 58, 237, 0.18);
}}
</style>
"""


def aplicar_tema() -> None:
    """Injeta o CSS do tema — chamar uma única vez, logo após set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)
