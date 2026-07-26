"""Testes do script de bootstrap do primeiro administrador.

São de integração porque o script fala com o banco diretamente — é o único
caminho pelo qual um admin nasce sem outro admin para aprová-lo, e um erro
aqui só apareceria no pior momento: com o sistema instalado e ninguém capaz
de entrar.

O terminal é simulado (`getpass` e `isatty` trocados), de modo que a senha
nunca chega a ser digitada de verdade.
"""
from unittest.mock import patch

import pytest

from acervo.auth import senhas
from acervo.persistence.db import cursor
from acervo.persistence.repository import UsuarioRepository
from scripts import criar_admin

pytestmark = pytest.mark.integration

SENHA = "acervo2026"
OUTRA_SENHA = "outrasenha9"
HASH_FALSO = "$argon2id$v=19$m=19456,t=2,p=1$hash-de-teste"


@pytest.fixture
def repo(schema_teste):
    return UsuarioRepository(schema_teste)


@pytest.fixture(autouse=True)
def _terminal_interativo(monkeypatch):
    monkeypatch.setattr(criar_admin.sys.stdin, "isatty", lambda: True)


@pytest.fixture(autouse=True)
def _limpar_usuarios(schema_teste):
    yield
    with cursor() as cur:
        cur.execute(f'DELETE FROM "{schema_teste}".usuarios')


def _digitando(*respostas):
    """Simula o que a pessoa digita nos prompts de senha, na ordem."""
    return patch.object(criar_admin.getpass, "getpass", side_effect=list(respostas))


def _conta(repo, email="chefe@exemplo.com"):
    with cursor() as cur:
        return repo.buscar_por_email(cur, email)


# ------------------------------------------------------------------- criação

def test_cria_o_primeiro_admin_ja_aprovado(repo, schema_teste):
    """Sem isto o sistema fica sem porta de entrada: o cadastro nasceria
    pendente e não haveria ninguém para aprová-lo."""
    with _digitando(SENHA, SENHA):
        criar_admin.criar_admin("Chefe@Exemplo.com ", "Nome do Chefe", schema=schema_teste)

    usuario, hash_guardado = _conta(repo)
    assert usuario.email == "chefe@exemplo.com"      # normalizado
    assert usuario.eh_admin and usuario.tem_acesso
    assert usuario.senha_temporaria is False         # é a senha definitiva dele
    assert senhas.conferir(SENHA, hash_guardado) is True


def test_criar_sem_nome_e_recusado(repo, schema_teste):
    """Errar o e-mail em uma promoção não pode virar uma conta nova sem querer."""
    with pytest.raises(SystemExit, match="--nome"):
        criar_admin.criar_admin("chefe@exemplo.com", schema=schema_teste)

    assert _conta(repo) is None


def test_email_invalido_nao_cria_nada(repo, schema_teste):
    from acervo.core.exceptions import CadastroError

    with pytest.raises(CadastroError):
        criar_admin.criar_admin("sem-arroba", "Nome do Chefe", schema=schema_teste)


# ---------------------------------------------------------------- promoção

def test_promove_conta_existente_sem_pedir_senha(repo, schema_teste):
    """Quem já se cadastrou pela tela não precisa de conta nova nem de senha
    nova — e o script não pode sobrescrever a senha que a pessoa escolheu."""
    with cursor() as cur:
        repo.criar(cur, "Chefe", "chefe@exemplo.com", senhas.gerar_hash(SENHA))

    with patch.object(criar_admin.getpass, "getpass", side_effect=AssertionError("não pedir senha")):
        criar_admin.criar_admin("chefe@exemplo.com", schema=schema_teste)

    usuario, hash_guardado = _conta(repo)
    assert usuario.eh_admin and usuario.tem_acesso
    assert senhas.conferir(SENHA, hash_guardado) is True


def test_promove_admin_bloqueado_de_volta_ao_acesso(repo, schema_teste):
    """A saída de emergência do sistema: se o último admin for bloqueado por
    engano, ainda dá para reativá-lo pelo servidor."""
    with cursor() as cur:
        criado = repo.criar(
            cur, "Chefe", "chefe@exemplo.com", HASH_FALSO, papel="admin", status="bloqueado",
        )

    criar_admin.criar_admin("chefe@exemplo.com", schema=schema_teste)

    with cursor() as cur:
        assert repo.buscar_por_id(cur, criado.id).tem_acesso is True


def test_rodar_duas_vezes_nao_muda_nada(repo, schema_teste, capsys):
    with _digitando(SENHA, SENHA):
        criar_admin.criar_admin("chefe@exemplo.com", "Nome do Chefe", schema=schema_teste)
    antes, hash_antes = _conta(repo)

    criar_admin.criar_admin("chefe@exemplo.com", schema=schema_teste)

    depois, hash_depois = _conta(repo)
    assert (depois.id, depois.papel, depois.status) == (antes.id, antes.papel, antes.status)
    assert hash_depois == hash_antes
    assert "nada a fazer" in capsys.readouterr().out


def test_redefinir_senha_de_admin_que_perdeu_o_acesso(repo, schema_teste):
    """O único caminho de volta para um admin que esqueceu a senha — não há
    outro admin para resetá-la pelo painel."""
    with cursor() as cur:
        criado = repo.criar(
            cur, "Chefe", "chefe@exemplo.com", senhas.gerar_hash(SENHA),
            papel="admin", status="aprovado",
        )

    with _digitando(OUTRA_SENHA, OUTRA_SENHA):
        criar_admin.criar_admin("chefe@exemplo.com", redefinir_senha=True, schema=schema_teste)

    usuario, hash_guardado = _conta(repo)
    assert usuario.id == criado.id
    assert senhas.conferir(OUTRA_SENHA, hash_guardado) is True
    assert senhas.conferir(SENHA, hash_guardado) is False
    # Não é senha temporária: quem digitou foi o próprio dono, no servidor.
    assert usuario.senha_temporaria is False


# -------------------------------------------------------- leitura da senha

def test_senha_fraca_e_recusada_ate_desistir(repo, schema_teste):
    with _digitando("123", "abc", "curta"):
        with pytest.raises(SystemExit, match="3 tentativas"):
            criar_admin.criar_admin("chefe@exemplo.com", "Nome do Chefe", schema=schema_teste)

    assert _conta(repo) is None


def test_confirmacao_divergente_pede_de_novo(repo, schema_teste):
    """Errar a confirmação não pode gravar a senha errada — seria um bloqueio
    silencioso da própria conta de administrador."""
    with _digitando(SENHA, "acervo2027", SENHA, SENHA):
        criar_admin.criar_admin("chefe@exemplo.com", "Nome do Chefe", schema=schema_teste)

    _, hash_guardado = _conta(repo)
    assert senhas.conferir(SENHA, hash_guardado) is True


def test_sem_terminal_o_script_para(repo, schema_teste, monkeypatch):
    """Fora de um terminal o getpass ecoa o que é digitado; melhor recusar
    do que imprimir a senha do administrador na saída do processo."""
    monkeypatch.setattr(criar_admin.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit, match="terminal interativo"):
        criar_admin.criar_admin("chefe@exemplo.com", "Nome do Chefe", schema=schema_teste)

    assert _conta(repo) is None
