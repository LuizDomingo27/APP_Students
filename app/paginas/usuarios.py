"""Painel do administrador — quem entra no acervo e quem deixa de entrar.

Esta página só desenha e chama; nenhuma regra de permissão nasce aqui. Cada
botão é uma função de `acervo.auth.admin_service`, que reconfere no banco se
quem clicou ainda é admin, se a transição de status faz sentido e se a ação
não deixaria o sistema sem nenhum administrador. Por isso os erros vindos de
lá são exibidos como estão: eles já foram escritos para serem lidos.

O que a interface decide sozinha é só o que *não* mostrar — os botões de uma
ação que a pessoa não pode fazer em si mesma, por exemplo. Isso poupa um
clique inútil, não substitui a barreira.
"""
import html
from typing import Callable, Optional, Sequence

import streamlit as st

from acervo.auth import admin_service
from acervo.core.exceptions import AcervoError
from acervo.core.models import Usuario
from app import componentes as comp
from app import sessao, tema

# (id do usuário, senha em claro) da última senha resetada. Fica no
# `session_state` porque o reset dispara um rerun e a senha precisa
# sobreviver a ele — mas só a ele: recarregar a página a perde, e a única
# saída é gerar outra. O banco nunca teve a senha em claro.
_SENHA_GERADA = "usuarios_senha_gerada"

_CORES_STATUS = {
    "pendente": tema.AMBAR,
    "aprovado": tema.VERDE,
    "recusado": tema.ROSA,
    "bloqueado": tema.TEXTO_SUAVE,
}

_ROTULOS_STATUS = {
    "pendente": "aguardando aprovação",
    "aprovado": "ativo",
    "recusado": "recusado",
    "bloqueado": "bloqueado",
}


def _executar(acao: Callable[[], None], sucesso: str) -> None:
    """Roda a ação e recarrega a página; se der erro, mostra e fica onde está.

    O rerun no sucesso é o que faz a lista refletir a mudança. No erro ele
    não acontece de propósito: a mensagem precisa continuar na tela.
    """
    try:
        acao()
    except AcervoError as e:
        st.error(str(e))
    else:
        st.toast(sucesso, icon="🟣")
        st.rerun()


def _resetar_senha(ator: Usuario, alvo: Usuario) -> None:
    try:
        _, temporaria = admin_service.resetar_senha(ator, alvo.id)
    except AcervoError as e:
        st.error(str(e))
    else:
        st.session_state[_SENHA_GERADA] = (alvo.id, temporaria)
        st.rerun()


def _senha_temporaria_em_cartaz(alvo: Usuario) -> None:
    """Mostra a senha recém-gerada — uma vez, e só para este usuário."""
    gerada = st.session_state.get(_SENHA_GERADA)
    if not gerada or gerada[0] != alvo.id:
        return

    st.warning(
        f"**Senha temporária de {alvo.nome}:** `{gerada[1]}`\n\n"
        "Anote agora e entregue em mãos — ela aparece uma vez só. "
        f"{comp.primeiro_nome(alvo.nome)} vai ter que definir uma senha própria "
        "antes de usar o acervo."
    )
    if st.button("Já anotei, pode esconder", key=f"esconder_senha_{alvo.id}"):
        st.session_state.pop(_SENHA_GERADA, None)
        st.rerun()


def _identificacao(usuario: Usuario, *, eu: bool) -> str:
    chips = [comp.chip_html(_ROTULOS_STATUS[usuario.status], _CORES_STATUS[usuario.status])]
    if usuario.eh_admin:
        chips.append(comp.chip_html("admin", tema.CIANO))
    if usuario.senha_temporaria:
        chips.append(comp.chip_html("senha temporária", tema.AMBAR))
    if eu:
        chips.append(comp.chip_html("você", tema.ROXO))

    return (
        '<div class="card-topo">'
        f'<span class="card-titulo">{html.escape(usuario.nome)}</span>'
        f'{"".join(chips)}'
        "</div>"
        f'<div class="card-caminho">{html.escape(usuario.email)}</div>'
        '<div class="card-meta">'
        f"cadastro em {comp.formatar_data(usuario.criado_em)} · "
        f"último acesso: {comp.formatar_data(usuario.ultimo_acesso)}"
        "</div>"
    )


def _botoes(ator: Usuario, alvo: Usuario) -> None:
    """As ações possíveis a partir do status atual de `alvo`."""
    if alvo.status == "pendente":
        col_a, col_b, _ = st.columns([1, 1, 3])
        if col_a.button("Aprovar", key=f"aprovar_{alvo.id}", type="primary", width="stretch"):
            _executar(
                lambda: admin_service.aprovar(ator, alvo.id),
                f"{comp.primeiro_nome(alvo.nome)} agora tem acesso.",
            )
        if col_b.button("Recusar", key=f"recusar_{alvo.id}", width="stretch"):
            _executar(
                lambda: admin_service.recusar(ator, alvo.id),
                f"Cadastro de {comp.primeiro_nome(alvo.nome)} recusado.",
            )
        return

    if alvo.status == "aprovado":
        col_a, col_b, col_c, _ = st.columns([1, 1.1, 1.2, 1.7])
        if col_a.button("Bloquear", key=f"bloquear_{alvo.id}", width="stretch"):
            _executar(
                lambda: admin_service.bloquear(ator, alvo.id),
                f"{comp.primeiro_nome(alvo.nome)} perdeu o acesso.",
            )
        if col_b.button("Resetar senha", key=f"resetar_{alvo.id}", width="stretch"):
            _resetar_senha(ator, alvo)

        virar = "usuario" if alvo.eh_admin else "admin"
        rotulo = "Remover admin" if alvo.eh_admin else "Tornar admin"
        if col_c.button(rotulo, key=f"papel_{alvo.id}", width="stretch"):
            _executar(
                lambda: admin_service.definir_papel(ator, alvo.id, virar),
                f"{comp.primeiro_nome(alvo.nome)} agora é '{virar}'.",
            )
        return

    # recusado ou bloqueado — o caminho de volta é o mesmo, muda o rótulo
    rotulo = "Reativar" if alvo.status == "bloqueado" else "Aprovar mesmo assim"
    col_a, _ = st.columns([1.4, 3.6])
    if col_a.button(rotulo, key=f"reativar_{alvo.id}", type="primary", width="stretch"):
        _executar(
            lambda: admin_service.reativar(ator, alvo.id),
            f"{comp.primeiro_nome(alvo.nome)} voltou a ter acesso.",
        )


def _cartao(ator: Usuario, alvo: Usuario) -> None:
    eu = alvo.id == ator.id
    with st.container(key=f"card_usuario_{alvo.id}"):
        st.markdown(_identificacao(alvo, eu=eu), unsafe_allow_html=True)
        _senha_temporaria_em_cartaz(alvo)
        if eu:
            # As ações sobre si mesmo são justamente as que o serviço barra
            # (ninguém se bloqueia, se rebaixa ou reseta a própria senha por
            # aqui). Mostrar os botões só renderia mensagens de erro.
            st.caption("Sua própria conta — use o menu da conta para trocar a senha.")
        else:
            _botoes(ator, alvo)


def _lista(ator: Usuario, usuarios: Sequence[Usuario], vazio: str) -> None:
    if not usuarios:
        st.info(vazio)
        return
    for alvo in usuarios:
        _cartao(ator, alvo)


def rotulo_aba(nome: str, quantos: int) -> str:
    """"Pendentes (3)" — sem número quando a aba está vazia, para não poluir."""
    return f"{nome} ({quantos})" if quantos else nome


def agrupar_por_situacao(
    usuarios: Sequence[Usuario],
) -> tuple[list[Usuario], list[Usuario], list[Usuario]]:
    """(pendentes, ativos, inativos) — as três abas do painel.

    Recusado e bloqueado dividem a mesma aba: são finais diferentes, mas a
    pergunta do admin é a mesma ("quem está de fora?") e a ação também.
    """
    pendentes = [u for u in usuarios if u.status == "pendente"]
    ativos = [u for u in usuarios if u.status == "aprovado"]
    inativos = [u for u in usuarios if u.status in ("recusado", "bloqueado")]
    return pendentes, ativos, inativos


def render() -> None:
    ator: Optional[Usuario] = sessao.usuario_atual()
    if ator is None or not ator.eh_admin:
        st.error("Esta página é restrita a administradores.")
        return

    st.markdown("### Usuários")
    st.caption(
        "Quem pede cadastro entra como pendente e não vê nada do acervo até "
        "alguém aprovar. Nada aqui apaga registro: recusar e bloquear são status."
    )
    st.write("")

    try:
        # Uma consulta só; os grupos saem daqui de dentro. O contador da aba
        # vem da mesma lista, para não haver chance de badge e conteúdo
        # discordarem.
        usuarios = admin_service.listar_usuarios(ator)
    except AcervoError as e:
        st.error(str(e))
        return

    pendentes, ativos, inativos = agrupar_por_situacao(usuarios)

    aba_pendentes, aba_ativos, aba_inativos = st.tabs([
        rotulo_aba("Pendentes", len(pendentes)),
        rotulo_aba("Ativos", len(ativos)),
        rotulo_aba("Recusados e bloqueados", len(inativos)),
    ])

    with aba_pendentes:
        _lista(ator, pendentes, "Nenhum cadastro esperando decisão.")
    with aba_ativos:
        _lista(ator, ativos, "Ninguém com acesso ainda.")
    with aba_inativos:
        _lista(ator, inativos, "Nenhum cadastro recusado ou bloqueado.")
