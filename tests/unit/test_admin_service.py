"""Testa a gestão de usuários pelo admin, com repositório em memória.

Duas famílias de teste dominam o arquivo: quem *pode* agir (o ator é sempre
reconferido no banco) e quais transições de status *existem* — o resto é
consequência.
"""
from unittest.mock import patch

import pytest

from acervo.auth import admin_service, senhas
from acervo.core.exceptions import PermissaoError
from tests.unit.fakes import FakeUsuarioRepo, cursor_fake


@pytest.fixture
def repo():
    return FakeUsuarioRepo()


@pytest.fixture(autouse=True)
def _sem_banco():
    with patch.object(admin_service, "cursor", cursor_fake):
        yield


@pytest.fixture
def admin(repo):
    return repo.semear("Admin", "admin@exemplo.com", papel="admin", status="aprovado")


def _pendente(repo, nome="Ana", email="ana@exemplo.com"):
    return repo.semear(nome, email)


def _aprovado(repo, nome="Bia", email="bia@exemplo.com", papel="usuario"):
    return repo.semear(nome, email, papel=papel, status="aprovado")


def _estado(repo, usuario_id):
    with cursor_fake() as cur:
        return repo.buscar_por_id(cur, usuario_id)


# --------------------------------------------------------------- permissão

def test_usuario_comum_nao_administra(repo, admin):
    comum = _aprovado(repo)
    alvo = _pendente(repo, "Ana", "ana@exemplo.com")

    for acao in (admin_service.aprovar, admin_service.recusar, admin_service.bloquear):
        with pytest.raises(PermissaoError, match="restrita a administradores"):
            acao(comum, alvo.id, usuarios_repo=repo)


def test_sem_ator_nao_administra(repo):
    alvo = _pendente(repo)
    with pytest.raises(PermissaoError):
        admin_service.aprovar(None, alvo.id, usuarios_repo=repo)


def test_admin_bloqueado_nao_administra(repo):
    bloqueado = repo.semear("Ex", "ex@exemplo.com", papel="admin", status="bloqueado")
    alvo = _pendente(repo)

    with pytest.raises(PermissaoError):
        admin_service.aprovar(bloqueado, alvo.id, usuarios_repo=repo)


def test_sessao_de_admin_revogada_perde_o_poder_na_hora(repo, admin):
    """A sessão vive em memória e não expira enquanto a aba estiver aberta.
    Quem teve o acesso revogado não pode continuar aprovando cadastros pela
    aba que deixou aberta — quem decide é a linha do banco, não a fotografia
    do login."""
    outro_admin = repo.semear("Chefe", "chefe@exemplo.com", papel="admin", status="aprovado")
    alvo = _pendente(repo)

    # `admin` continua com o objeto antigo em mãos, mas foi bloqueado no banco.
    admin_service.bloquear(outro_admin, admin.id, usuarios_repo=repo)

    assert admin.eh_admin and admin.tem_acesso  # a fotografia ainda diz "admin ativo"
    with pytest.raises(PermissaoError, match="restrita a administradores"):
        admin_service.aprovar(admin, alvo.id, usuarios_repo=repo)


def test_admin_rebaixado_perde_o_poder_na_hora(repo, admin):
    outro_admin = repo.semear("Chefe", "chefe@exemplo.com", papel="admin", status="aprovado")
    alvo = _pendente(repo)

    admin_service.definir_papel(outro_admin, admin.id, "usuario", usuarios_repo=repo)

    with pytest.raises(PermissaoError):
        admin_service.aprovar(admin, alvo.id, usuarios_repo=repo)


def test_alvo_inexistente(repo, admin):
    with pytest.raises(PermissaoError, match="não encontrado"):
        admin_service.aprovar(admin, 999_999, usuarios_repo=repo)


# --------------------------------------------------------------- listagem

def test_listar_e_contar_exigem_admin(repo):
    comum = _aprovado(repo)
    with pytest.raises(PermissaoError):
        admin_service.listar_usuarios(comum, usuarios_repo=repo)
    with pytest.raises(PermissaoError):
        admin_service.contar_por_status(comum, usuarios_repo=repo)


def test_listar_e_contar_para_o_painel(repo, admin):
    _pendente(repo)
    _aprovado(repo)

    todos = admin_service.listar_usuarios(admin, usuarios_repo=repo)
    pendentes = admin_service.listar_usuarios(admin, status="pendente", usuarios_repo=repo)

    assert todos[0].status == "pendente"          # o que exige ação vem primeiro
    assert len(pendentes) == 1
    assert admin_service.contar_por_status(admin, usuarios_repo=repo) == {
        "pendente": 1, "aprovado": 2,
    }


# -------------------------------------------------------------- transições

def test_aprovar_pendente_libera_acesso_e_carimba_quem_decidiu(repo, admin):
    ana = _pendente(repo)

    atualizado = admin_service.aprovar(admin, ana.id, usuarios_repo=repo)

    assert atualizado.tem_acesso is True
    assert repo.decisoes == [(ana.id, "aprovado", admin.id)]


def test_recusar_pendente_nao_apaga_o_cadastro(repo, admin):
    ana = _pendente(repo)

    atualizado = admin_service.recusar(admin, ana.id, usuarios_repo=repo)

    assert atualizado.status == "recusado"
    assert atualizado.nome == "Ana"
    assert _estado(repo, ana.id) is not None


def test_recusado_pode_ser_aprovado_depois(repo, admin):
    """O admin pode mudar de ideia sem a pessoa precisar recadastrar."""
    ana = _pendente(repo)
    admin_service.recusar(admin, ana.id, usuarios_repo=repo)

    assert admin_service.aprovar(admin, ana.id, usuarios_repo=repo).tem_acesso is True


def test_bloquear_e_reativar_aprovado(repo, admin):
    bia = _aprovado(repo)

    assert admin_service.bloquear(admin, bia.id, usuarios_repo=repo).status == "bloqueado"
    assert admin_service.reativar(admin, bia.id, usuarios_repo=repo).tem_acesso is True


@pytest.mark.parametrize(
    "status_inicial, acao, trecho",
    [
        ("aprovado", admin_service.recusar, "status 'aprovado'"),
        ("pendente", admin_service.bloquear, "status 'pendente'"),
        ("recusado", admin_service.bloquear, "status 'recusado'"),
    ],
)
def test_transicoes_inexistentes_sao_recusadas(repo, admin, status_inicial, acao, trecho):
    """A máquina de estados da migração 0004 vale também no serviço: bloquear
    é para quem tem acesso, recusar é para quem ainda está na fila."""
    alvo = repo.semear("Alvo", "alvo@exemplo.com", status=status_inicial)

    with pytest.raises(PermissaoError, match=trecho):
        acao(admin, alvo.id, usuarios_repo=repo)


def test_repetir_o_status_atual_e_recusado(repo, admin):
    bia = _aprovado(repo)

    with pytest.raises(PermissaoError, match="já está com o status"):
        admin_service.aprovar(admin, bia.id, usuarios_repo=repo)


@pytest.mark.parametrize("acao", [admin_service.recusar, admin_service.bloquear])
def test_admin_nao_se_derruba(repo, admin, acao):
    """Caminho mais curto para um acidente irreversível — barrado antes de
    qualquer ida ao banco."""
    with pytest.raises(PermissaoError, match="a si mesmo"):
        acao(admin, admin.id, usuarios_repo=repo)


# ------------------------------------------------------------------ papéis

def test_promover_usuario_aprovado(repo, admin):
    bia = _aprovado(repo)

    assert admin_service.definir_papel(admin, bia.id, "admin", usuarios_repo=repo).eh_admin


def test_promover_exige_conta_aprovada(repo, admin):
    """Promover quem está na fila pularia a aprovação pela porta dos fundos."""
    ana = _pendente(repo)

    with pytest.raises(PermissaoError, match="aprovado"):
        admin_service.definir_papel(admin, ana.id, "admin", usuarios_repo=repo)


def test_rebaixar_outro_admin(repo, admin):
    outro = _aprovado(repo, "Outro", "outro@exemplo.com", papel="admin")

    assert admin_service.definir_papel(admin, outro.id, "usuario", usuarios_repo=repo).eh_admin is False


def test_admin_nao_altera_o_proprio_papel(repo, admin):
    with pytest.raises(PermissaoError, match="seu próprio papel"):
        admin_service.definir_papel(admin, admin.id, "usuario", usuarios_repo=repo)


def test_papel_inexistente_e_recusado(repo, admin):
    bia = _aprovado(repo)
    with pytest.raises(PermissaoError, match="Papel inválido"):
        admin_service.definir_papel(admin, bia.id, "superusuario", usuarios_repo=repo)


def test_repetir_o_papel_atual_e_recusado(repo, admin):
    bia = _aprovado(repo)
    with pytest.raises(PermissaoError, match="já é"):
        admin_service.definir_papel(admin, bia.id, "usuario", usuarios_repo=repo)


def test_invariante_de_nunca_ficar_sem_administrador(repo, admin):
    """Guarda de fundo de poço, exercitada direto.

    Pelo serviço ela é hoje inalcançável (o ator é revalidado no banco e não
    pode agir sobre si mesmo, então sempre resta ao menos ele) — mas a
    invariante é importante demais para depender dessas duas regras
    continuarem verdadeiras.
    """
    with cursor_fake() as cur:
        with pytest.raises(PermissaoError, match="último administrador"):
            admin_service._exigir_outro_admin_ativo(cur, repo, admin, "bloquear")

        # com outro admin ativo, a mesma checagem libera
        repo.semear("Outro", "outro@exemplo.com", papel="admin", status="aprovado")
        admin_service._exigir_outro_admin_ativo(cur, repo, admin, "bloquear")


# ---------------------------------------------------------- reset de senha

def test_resetar_senha_devolve_senha_usavel_e_obriga_a_troca(repo, admin):
    bia = _aprovado(repo)

    atualizado, temporaria = admin_service.resetar_senha(admin, bia.id, usuarios_repo=repo)

    assert atualizado.senha_temporaria is True
    assert senhas.validar_senha(temporaria) is None
    assert senhas.conferir(temporaria, repo.hash_de(bia.id)) is True


def test_reset_guarda_apenas_o_hash(repo, admin):
    """A senha em claro só existe no retorno da função — recarregar o painel
    não a traz de volta."""
    bia = _aprovado(repo)

    _, temporaria = admin_service.resetar_senha(admin, bia.id, usuarios_repo=repo)

    assert temporaria not in repo.hash_de(bia.id)


def test_admin_nao_reseta_a_propria_senha(repo, admin):
    with pytest.raises(PermissaoError, match="sua própria senha"):
        admin_service.resetar_senha(admin, admin.id, usuarios_repo=repo)


def test_resetar_senha_exige_admin(repo):
    comum = _aprovado(repo)
    alvo = _pendente(repo)

    with pytest.raises(PermissaoError):
        admin_service.resetar_senha(comum, alvo.id, usuarios_repo=repo)
