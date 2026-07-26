"""Gestão de usuários pelo administrador.

Toda função recebe o `ator` (quem está agindo) e confere o papel dele antes
de qualquer coisa. A verificação vive aqui, e não na interface, porque
esconder um botão é conveniência visual — a barreira de verdade precisa
estar na camada que fala com o banco.

Quatro salvaguardas atravessam o módulo:

  - **O poder do ator é reconferido no banco a cada ação.** A sessão vive em
    memória e não expira enquanto a aba estiver aberta; sem esta releitura,
    um admin que tivesse o acesso revogado continuaria aprovando cadastros
    pela aba que deixou aberta.
  - **Ninguém se derruba sozinho.** Um admin não pode se recusar, bloquear
    nem se rebaixar; seria o caminho mais curto para um acidente irreversível.
  - **Sempre resta um administrador.** Nenhuma ação pode deixar o sistema sem
    ninguém capaz de aprovar cadastros — o que exigiria voltar ao servidor e
    rodar o script de bootstrap.
  - **Nada é apagado.** Recusar e bloquear são status; o cadastro permanece,
    com o registro de quem decidiu e quando.
"""
import logging
from typing import Optional

from acervo.auth import senhas
from acervo.core.exceptions import PermissaoError
from acervo.core.models import Usuario
from acervo.persistence.db import cursor
from acervo.persistence.repository import UsuarioRepository

logger = logging.getLogger("acervo.admin")

PAPEIS = ("usuario", "admin")

# De quais status cada destino pode ser alcançado. É a máquina de estados da
# migração 0004 escrita em Python: o banco garante que o valor existe, isto
# garante que o caminho até ele faz sentido.
_ORIGENS_PERMITIDAS = {
    "aprovado": {"pendente", "recusado", "bloqueado"},
    "recusado": {"pendente"},
    "bloqueado": {"aprovado"},
}

_NOME_DA_ACAO = {
    "aprovado": "aprovar",
    "recusado": "recusar",
    "bloqueado": "bloquear",
}


_RESTRITO_A_ADMINS = "Esta ação é restrita a administradores."


def _exigir_admin(ator: Optional[Usuario]) -> None:
    """Pré-checagem barata, sem ida ao banco. Não é a barreira final."""
    if ator is None or not ator.eh_admin or not ator.tem_acesso:
        raise PermissaoError(_RESTRITO_A_ADMINS)


def _admin_atual(cur, repo: UsuarioRepository, ator: Usuario) -> Usuario:
    """Relê o ator no banco e devolve a linha fresca — a barreira de verdade.

    O `Usuario` que chega aqui veio do `session_state`, que é uma fotografia
    do momento do login e não expira enquanto a aba estiver aberta. Se, desde
    então, outro administrador tiver bloqueado ou rebaixado esta pessoa, o
    objeto em memória ainda diria 'admin aprovado'. Quem decide é a linha do
    banco, sempre.
    """
    atual = repo.buscar_por_id(cur, ator.id) if ator and ator.id else None
    if atual is None or not atual.eh_admin or not atual.tem_acesso:
        raise PermissaoError(_RESTRITO_A_ADMINS)
    return atual


def _buscar_alvo(cur, repo: UsuarioRepository, usuario_id: int) -> Usuario:
    alvo = repo.buscar_por_id(cur, usuario_id)
    if alvo is None:
        raise PermissaoError("Usuário não encontrado.")
    return alvo


def _exigir_outro_admin_ativo(cur, repo: UsuarioRepository, alvo: Usuario, acao: str) -> None:
    """Barra a ação se ela deixaria o sistema sem nenhum admin ativo.

    Hoje esta checagem é redundante: como o ator é revalidado no banco e não
    pode agir sobre si mesmo, sempre resta ao menos ele. Ela fica porque a
    invariante "existe pelo menos um administrador" é importante demais para
    depender de duas outras regras continuarem verdadeiras — se um dia
    surgir uma ação em lote ou um ator de serviço, é aqui que ela segura.
    """
    if not (alvo.eh_admin and alvo.tem_acesso):
        return
    if repo.contar_admins_ativos(cur, exceto=alvo.id) == 0:
        raise PermissaoError(
            f"Não é possível {acao} o último administrador ativo — "
            "promova outro administrador antes."
        )


def listar_usuarios(
    ator: Usuario,
    status: Optional[str] = None,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> tuple[Usuario, ...]:
    _exigir_admin(ator)
    repo = usuarios_repo or UsuarioRepository(schema)
    with cursor() as cur:
        _admin_atual(cur, repo, ator)
        return repo.listar(cur, status=status)


def contar_por_status(
    ator: Usuario,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> dict[str, int]:
    """{status: quantidade} — o painel usa para o contador de pendentes."""
    _exigir_admin(ator)
    repo = usuarios_repo or UsuarioRepository(schema)
    with cursor() as cur:
        _admin_atual(cur, repo, ator)
        return repo.contar_por_status(cur)


def _mudar_status(
    ator: Usuario,
    usuario_id: int,
    destino: str,
    *,
    schema: str,
    usuarios_repo: Optional[UsuarioRepository],
) -> Usuario:
    _exigir_admin(ator)
    acao = _NOME_DA_ACAO[destino]

    if ator.id == usuario_id and destino != "aprovado":
        raise PermissaoError(f"Você não pode {acao} a si mesmo.")

    repo = usuarios_repo or UsuarioRepository(schema)
    with cursor() as cur:
        ator = _admin_atual(cur, repo, ator)
        alvo = _buscar_alvo(cur, repo, usuario_id)

        if alvo.status == destino:
            raise PermissaoError(f"{alvo.nome} já está com o status '{destino}'.")
        if alvo.status not in _ORIGENS_PERMITIDAS[destino]:
            raise PermissaoError(
                f"Não é possível {acao} um cadastro com status '{alvo.status}'."
            )
        if destino in ("recusado", "bloqueado"):
            _exigir_outro_admin_ativo(cur, repo, alvo, acao)

        repo.atualizar_status(cur, usuario_id, destino, decidido_por=ator.id)
        atualizado = repo.buscar_por_id(cur, usuario_id)

    logger.info("%s: %s -> %s (por %s)", acao, alvo.email, destino, ator.email)
    return atualizado


def aprovar(
    ator: Usuario,
    usuario_id: int,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Libera o acesso de um cadastro pendente, recusado ou bloqueado."""
    return _mudar_status(
        ator, usuario_id, "aprovado", schema=schema, usuarios_repo=usuarios_repo,
    )


def reativar(
    ator: Usuario,
    usuario_id: int,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Devolve o acesso a quem foi bloqueado.

    É a mesma transição de `aprovar` vista de outro estado — existe como
    função própria só para o painel poder rotular o botão corretamente.
    """
    return aprovar(ator, usuario_id, schema=schema, usuarios_repo=usuarios_repo)


def recusar(
    ator: Usuario,
    usuario_id: int,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Nega um cadastro pendente. O registro fica, com o motivo implícito no status."""
    return _mudar_status(
        ator, usuario_id, "recusado", schema=schema, usuarios_repo=usuarios_repo,
    )


def bloquear(
    ator: Usuario,
    usuario_id: int,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Revoga o acesso de alguém já aprovado, sem apagar o cadastro."""
    return _mudar_status(
        ator, usuario_id, "bloqueado", schema=schema, usuarios_repo=usuarios_repo,
    )


def definir_papel(
    ator: Usuario,
    usuario_id: int,
    papel: str,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Promove a admin ou rebaixa a usuário comum."""
    _exigir_admin(ator)
    if papel not in PAPEIS:
        raise PermissaoError(f"Papel inválido: '{papel}'.")
    if ator.id == usuario_id:
        raise PermissaoError("Você não pode alterar o seu próprio papel.")

    repo = usuarios_repo or UsuarioRepository(schema)
    with cursor() as cur:
        ator = _admin_atual(cur, repo, ator)
        alvo = _buscar_alvo(cur, repo, usuario_id)

        if alvo.papel == papel:
            raise PermissaoError(f"{alvo.nome} já é '{papel}'.")
        if papel == "admin" and not alvo.tem_acesso:
            raise PermissaoError("Só um usuário aprovado pode virar administrador.")
        if papel == "usuario":
            _exigir_outro_admin_ativo(cur, repo, alvo, "rebaixar")

        repo.atualizar_papel(cur, usuario_id, papel)
        atualizado = repo.buscar_por_id(cur, usuario_id)

    logger.info("Papel alterado: %s -> %s (por %s)", alvo.email, papel, ator.email)
    return atualizado


def resetar_senha(
    ator: Usuario,
    usuario_id: int,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> tuple[Usuario, str]:
    """Gera uma senha temporária e devolve (usuário, senha em claro).

    A senha em claro só existe neste retorno — o banco guarda apenas o hash.
    O painel a mostra uma única vez para o admin repassar; recarregar a página
    não a traz de volta, e a única saída é gerar outra.

    O usuário entra com ela e é obrigado a definir uma senha própria antes de
    chegar a qualquer página (flag `senha_temporaria`).
    """
    _exigir_admin(ator)
    if ator.id == usuario_id:
        raise PermissaoError(
            "Para trocar a sua própria senha, use a opção de troca de senha da sua conta."
        )

    repo = usuarios_repo or UsuarioRepository(schema)
    temporaria = senhas.gerar_senha_temporaria()

    with cursor() as cur:
        ator = _admin_atual(cur, repo, ator)
        alvo = _buscar_alvo(cur, repo, usuario_id)
        repo.atualizar_senha(cur, usuario_id, senhas.gerar_hash(temporaria), temporaria=True)
        atualizado = repo.buscar_por_id(cur, usuario_id)

    logger.info("Senha resetada para %s (por %s)", alvo.email, ator.email)
    return atualizado, temporaria
