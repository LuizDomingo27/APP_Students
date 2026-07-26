"""Testa cadastro, login e troca de senha com repositório em memória.

O foco não é o "caminho feliz" (esse é fácil): é garantir que a tela de login
não conte nada a quem não provou identidade. Vários testes aqui existem só
para fixar *qual* mensagem sai em *qual* situação.
"""
from unittest.mock import patch

import pytest

from acervo.auth import auth_service, senhas
from acervo.core.exceptions import AutenticacaoError, CadastroError
from tests.unit.fakes import FakeUsuarioRepo, cursor_fake

SENHA = "acervo2026"
OUTRA_SENHA = "outrasenha9"


@pytest.fixture
def repo():
    return FakeUsuarioRepo()


@pytest.fixture(autouse=True)
def _sem_banco():
    with patch.object(auth_service, "cursor", cursor_fake):
        yield


def _semear_conta(repo, *, status="aprovado", papel="usuario", senha=SENHA, temporaria=False):
    return repo.semear(
        "Ana Silva", "ana@exemplo.com", senhas.gerar_hash(senha),
        papel=papel, status=status, senha_temporaria=temporaria,
    )


# ---------------------------------------------------------------- cadastro

def test_cadastro_nasce_pendente_e_sem_privilegio(repo):
    usuario = auth_service.cadastrar("Ana Silva", "ana@exemplo.com", SENHA, usuarios_repo=repo)

    assert usuario.status == "pendente"
    assert usuario.papel == "usuario"
    assert usuario.tem_acesso is False


def test_cadastro_normaliza_nome_e_email(repo):
    usuario = auth_service.cadastrar(
        "  Ana   Silva ", "  Ana@EXEMPLO.com ", SENHA, usuarios_repo=repo,
    )

    assert usuario.nome == "Ana Silva"
    assert usuario.email == "ana@exemplo.com"


def test_cadastro_grava_hash_e_nunca_a_senha(repo):
    usuario = auth_service.cadastrar("Ana Silva", "ana@exemplo.com", SENHA, usuarios_repo=repo)
    guardado = repo.hash_de(usuario.id)

    assert SENHA not in guardado
    assert guardado.startswith("$argon2id$")
    assert senhas.conferir(SENHA, guardado) is True


@pytest.mark.parametrize(
    "nome, email, senha",
    [
        ("A", "ana@exemplo.com", SENHA),           # nome curto
        ("Ana Silva", "sem-arroba", SENHA),        # e-mail malformado
        ("Ana Silva", "ana@exemplo.com", "abc"),   # senha curta
        ("Ana Silva", "ana@exemplo.com", "semnumeros"),
    ],
)
def test_cadastro_recusa_dados_invalidos(repo, nome, email, senha):
    with pytest.raises(CadastroError):
        auth_service.cadastrar(nome, email, senha, usuarios_repo=repo)


def test_cadastro_com_email_ja_usado_e_recusado(repo):
    auth_service.cadastrar("Ana Silva", "ana@exemplo.com", SENHA, usuarios_repo=repo)

    with pytest.raises(CadastroError, match="Já existe uma conta"):
        auth_service.cadastrar("Outra Ana", "ANA@exemplo.com", OUTRA_SENHA, usuarios_repo=repo)


def test_cadastro_invalido_nao_toca_o_repositorio(repo):
    with pytest.raises(CadastroError):
        auth_service.cadastrar("Ana Silva", "ana@exemplo.com", "fraca", usuarios_repo=repo)

    with cursor_fake() as cur:
        assert repo.listar(cur) == ()


# ------------------------------------------------------------------- login

def test_login_aprovado_devolve_usuario_e_registra_acesso(repo):
    conta = _semear_conta(repo)

    usuario = auth_service.autenticar("ana@exemplo.com", SENHA, usuarios_repo=repo)

    assert usuario.id == conta.id
    assert repo.acessos_registrados == [conta.id]


def test_login_aceita_email_com_maiusculas_e_espacos(repo):
    _semear_conta(repo)
    assert auth_service.autenticar("  ANA@Exemplo.COM ", SENHA, usuarios_repo=repo)


def test_login_com_senha_errada_e_recusado(repo):
    _semear_conta(repo)

    with pytest.raises(AutenticacaoError, match="E-mail ou senha incorretos"):
        auth_service.autenticar("ana@exemplo.com", OUTRA_SENHA, usuarios_repo=repo)

    assert repo.acessos_registrados == []


def test_email_inexistente_e_senha_errada_dao_a_mesma_mensagem(repo):
    """O núcleo da defesa contra enumeração de contas: se as mensagens
    diferissem, bastaria um formulário para descobrir quem tem cadastro."""
    _semear_conta(repo)

    with pytest.raises(AutenticacaoError) as senha_errada:
        auth_service.autenticar("ana@exemplo.com", OUTRA_SENHA, usuarios_repo=repo)
    with pytest.raises(AutenticacaoError) as nao_existe:
        auth_service.autenticar("ninguem@exemplo.com", SENHA, usuarios_repo=repo)
    with pytest.raises(AutenticacaoError) as malformado:
        auth_service.autenticar("nao-e-email", SENHA, usuarios_repo=repo)

    assert str(senha_errada.value) == str(nao_existe.value) == str(malformado.value)


def test_email_inexistente_gasta_o_mesmo_trabalho_de_um_login_real(repo):
    """Sem o hash dummy, um e-mail sem cadastro responderia instantaneamente
    e um real levaria os ~40 ms do Argon2 — um cronômetro faria a triagem."""
    with patch.object(senhas, "conferir", wraps=senhas.conferir) as espiao:
        with pytest.raises(AutenticacaoError):
            auth_service.autenticar("ninguem@exemplo.com", SENHA, usuarios_repo=repo)

    assert espiao.call_count == 1
    assert espiao.call_args.args[1] == senhas.hash_dummy()


@pytest.mark.parametrize(
    "status, trecho",
    [
        ("pendente", "aguarda aprovação"),
        ("recusado", "não foi aprovado"),
        ("bloqueado", "bloqueado"),
    ],
)
def test_conta_sem_acesso_explica_o_motivo_apos_a_senha_certa(repo, status, trecho):
    _semear_conta(repo, status=status)

    with pytest.raises(AutenticacaoError, match=trecho):
        auth_service.autenticar("ana@exemplo.com", SENHA, usuarios_repo=repo)


@pytest.mark.parametrize("status", ["pendente", "recusado", "bloqueado"])
def test_conta_sem_acesso_nao_revela_status_com_senha_errada(repo, status):
    """Se a mensagem 'aguardando aprovação' aparecesse antes de conferir a
    senha, ela própria denunciaria que aquele e-mail tem cadastro."""
    _semear_conta(repo, status=status)

    with pytest.raises(AutenticacaoError, match="E-mail ou senha incorretos"):
        auth_service.autenticar("ana@exemplo.com", OUTRA_SENHA, usuarios_repo=repo)


@pytest.mark.parametrize("status", ["pendente", "recusado", "bloqueado"])
def test_conta_sem_acesso_nao_registra_acesso(repo, status):
    _semear_conta(repo, status=status)

    with pytest.raises(AutenticacaoError):
        auth_service.autenticar("ana@exemplo.com", SENHA, usuarios_repo=repo)

    assert repo.acessos_registrados == []


def test_login_atualiza_hash_gerado_com_parametros_fracos(repo):
    """Endurecer o custo do Argon2 no futuro não exige migração nem obrigar
    ninguém a trocar de senha: o hash se atualiza sozinho no login."""
    from argon2 import PasswordHasher

    fraco = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(SENHA)
    conta = repo.semear("Ana", "ana@exemplo.com", fraco, status="aprovado")

    auth_service.autenticar("ana@exemplo.com", SENHA, usuarios_repo=repo)

    novo = repo.hash_de(conta.id)
    assert novo != fraco
    assert senhas.precisa_rehash(novo) is False
    assert senhas.conferir(SENHA, novo) is True


def test_rehash_preserva_a_marca_de_senha_temporaria(repo):
    """Quem entra com senha temporária e cai no rehash não pode escapar da
    troca obrigatória por causa disso."""
    from argon2 import PasswordHasher

    fraco = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(SENHA)
    conta = repo.semear(
        "Ana", "ana@exemplo.com", fraco, status="aprovado", senha_temporaria=True,
    )

    auth_service.autenticar("ana@exemplo.com", SENHA, usuarios_repo=repo)

    with cursor_fake() as cur:
        assert repo.buscar_por_id(cur, conta.id).senha_temporaria is True


# ------------------------------------------------------- troca de senha

def test_alterar_senha_troca_o_hash_e_limpa_a_marca_de_temporaria(repo):
    conta = _semear_conta(repo, temporaria=True)

    atualizado = auth_service.alterar_senha(conta, SENHA, OUTRA_SENHA, usuarios_repo=repo)

    assert atualizado.senha_temporaria is False
    assert senhas.conferir(OUTRA_SENHA, repo.hash_de(conta.id)) is True
    assert senhas.conferir(SENHA, repo.hash_de(conta.id)) is False


def test_alterar_senha_exige_a_senha_atual_correta(repo):
    """Impede que uma sessão esquecida aberta tome a conta em definitivo."""
    conta = _semear_conta(repo)

    with pytest.raises(AutenticacaoError, match="senha atual"):
        auth_service.alterar_senha(conta, "chute-errado-1", OUTRA_SENHA, usuarios_repo=repo)

    assert senhas.conferir(SENHA, repo.hash_de(conta.id)) is True


def test_alterar_senha_recusa_repetir_a_atual(repo):
    conta = _semear_conta(repo)

    with pytest.raises(CadastroError, match="diferente da atual"):
        auth_service.alterar_senha(conta, SENHA, SENHA, usuarios_repo=repo)


def test_alterar_senha_aplica_a_politica_de_senha(repo):
    conta = _semear_conta(repo)

    with pytest.raises(CadastroError):
        auth_service.alterar_senha(conta, SENHA, "fraca", usuarios_repo=repo)
