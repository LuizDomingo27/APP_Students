"""Tela de entrada — login e criação de conta.

É a única página que alguém sem sessão consegue ver, então tudo aqui vale
como texto público: nenhuma mensagem pode revelar quais e-mails têm cadastro.
As frases exibidas vêm prontas de `acervo.auth.auth_service`, que é onde essa
regra é decidida e testada; esta página só as repassa.
"""
import streamlit as st

from acervo.auth import auth_service, senhas
from acervo.core.exceptions import AcervoError, AutenticacaoError, CadastroError
from app import sessao

_AJUDA_SENHA = (
    f"Mínimo de {senhas.MIN_SENHA} caracteres, com ao menos uma letra e um número."
)


def _cabecalho() -> None:
    st.markdown(
        '<div class="acesso-cabecalho">'
        '<div class="marca"><span class="marca-ponto"></span>'
        'Acervo&nbsp;<span class="grad">DS</span></div>'
        '<p>Entre para pesquisar no acervo.</p>'
        "</div>",
        unsafe_allow_html=True,
    )


def _form_entrar() -> None:
    espera = sessao.espera_restante()

    with st.form("form_entrar", border=False):
        email = st.text_input("E-mail", placeholder="voce@exemplo.com")
        senha = st.text_input("Senha", type="password")
        enviar = st.form_submit_button(
            "Entrar", type="primary", width="stretch", disabled=espera > 0,
        )

    if espera > 0:
        st.caption(f"Muitas tentativas seguidas. Tente de novo em {espera}s.")
        # Sem este botão a página ficaria travada: o formulário está
        # desabilitado, e o contador só é reavaliado quando algo provoca um
        # rerun do Streamlit.
        if st.button("Já esperei, tentar de novo", width="stretch"):
            st.rerun()
        return

    if not enviar:
        return

    try:
        usuario = auth_service.autenticar(email, senha)
    except AutenticacaoError as e:
        # Conta o erro seja qual for o motivo, inclusive "aguarda aprovação".
        # Além de frear o chute de senha, isso impede que o próprio freio vire
        # um oráculo: se só senha errada contasse, dava para descobrir que um
        # e-mail existe observando quando o bloqueio aparece.
        sessao.registrar_falha()
        st.error(str(e))
    except AcervoError as e:
        st.error(f"Não foi possível falar com o banco agora: {e}")
    else:
        sessao.iniciar_sessao(usuario)
        st.rerun()


def _form_criar_conta() -> None:
    with st.form("form_criar_conta", border=False):
        nome = st.text_input("Nome completo")
        email = st.text_input("E-mail", placeholder="voce@exemplo.com")
        senha = st.text_input("Senha", type="password", help=_AJUDA_SENHA)
        confirmacao = st.text_input("Repita a senha", type="password")
        enviar = st.form_submit_button("Criar conta", type="primary", width="stretch")

    if not enviar:
        return

    if senha != confirmacao:
        st.error("As senhas não conferem.")
        return

    try:
        auth_service.cadastrar(nome, email, senha)
    except CadastroError as e:
        st.error(str(e))
    except AcervoError as e:
        st.error(f"Não foi possível falar com o banco agora: {e}")
    else:
        st.success(
            "**Cadastro enviado.** Um administrador precisa aprovar seu acesso — "
            "assim que isso acontecer, é só entrar com o e-mail e a senha que "
            "você acabou de escolher."
        )


def render() -> None:
    _, meio, _ = st.columns([1, 1.7, 1])
    with meio:
        with st.container(key="cartao_acesso"):
            _cabecalho()
            aba_entrar, aba_criar = st.tabs(["Entrar", "Criar conta"])
            with aba_entrar:
                _form_entrar()
            with aba_criar:
                _form_criar_conta()
