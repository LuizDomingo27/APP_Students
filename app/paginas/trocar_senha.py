"""Troca de senha do próprio usuário.

Serve a dois momentos: a troca voluntária, e a obrigatória de quem entrou com
a senha temporária que um admin gerou. No modo obrigatório esta é a única
página que o app mostra — a senha temporária circulou por fora do sistema
(foi ditada, colada em uma mensagem) e não pode virar a senha definitiva.
"""
import streamlit as st

from acervo.auth import auth_service, senhas
from acervo.core.exceptions import AcervoError, AutenticacaoError, CadastroError
from app import sessao

_AJUDA_SENHA = (
    f"Mínimo de {senhas.MIN_SENHA} caracteres, com ao menos uma letra e um número."
)


def render(*, obrigatoria: bool = False) -> None:
    usuario = sessao.usuario_atual()
    if usuario is None:
        return

    _, meio, _ = st.columns([1, 1.7, 1])
    with meio:
        with st.container(key="cartao_acesso"):
            if obrigatoria:
                st.markdown("### Defina sua senha")
                st.caption(
                    "Você entrou com uma senha temporária criada por um administrador. "
                    "Escolha uma senha sua para continuar."
                )
            else:
                st.markdown("### Trocar senha")
                st.caption(f"Conta: {usuario.email}")

            with st.form("form_trocar_senha", border=False):
                atual = st.text_input(
                    "Senha temporária" if obrigatoria else "Senha atual", type="password",
                )
                nova = st.text_input("Nova senha", type="password", help=_AJUDA_SENHA)
                confirmacao = st.text_input("Repita a nova senha", type="password")
                enviar = st.form_submit_button(
                    "Salvar nova senha", type="primary", width="stretch",
                )

            if not enviar:
                return

            if nova != confirmacao:
                st.error("As senhas não conferem.")
                return

            try:
                atualizado = auth_service.alterar_senha(usuario, atual, nova)
            except (AutenticacaoError, CadastroError) as e:
                st.error(str(e))
            except AcervoError as e:
                st.error(f"Não foi possível falar com o banco agora: {e}")
            else:
                sessao.atualizar_usuario(atualizado)
                st.toast("Senha alterada.", icon="🟣")
                st.rerun()
