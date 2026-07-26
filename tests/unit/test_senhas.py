"""Testa as regras puras de credencial (acervo/auth/senhas.py).

É o módulo mais sensível do sistema e o mais fácil de testar: nenhuma função
aqui toca banco, então tudo roda sem DATABASE_URL.
"""
import pytest

from acervo.auth import senhas
from acervo.core.exceptions import CadastroError

SENHA_OK = "acervo2026"


# ------------------------------------------------------------------ e-mail

@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("Ana@Exemplo.COM", "ana@exemplo.com"),
        ("  joao@exemplo.com  ", "joao@exemplo.com"),
        ("MARIA.SILVA@sub.dominio.com.br", "maria.silva@sub.dominio.com.br"),
    ],
)
def test_normalizar_email_canoniza(entrada, esperado):
    assert senhas.normalizar_email(entrada) == esperado


@pytest.mark.parametrize(
    "invalido",
    ["", "   ", "sem-arroba.com", "sem@dominio", "dois@@arrobas.com", "com espaco@x.com"],
)
def test_normalizar_email_recusa_malformado(invalido):
    with pytest.raises(CadastroError):
        senhas.normalizar_email(invalido)


def test_normalizar_email_recusa_longo_demais():
    gigante = "a" * (senhas.MAX_EMAIL) + "@exemplo.com"
    with pytest.raises(CadastroError):
        senhas.normalizar_email(gigante)


def test_email_normalizado_impede_conta_duplicada():
    """O UNIQUE do banco é sensível a maiúsculas — a normalização é o que
    garante que a mesma pessoa não crie duas contas."""
    assert senhas.normalizar_email("Ana@x.com") == senhas.normalizar_email("ana@X.COM")


# -------------------------------------------------------------------- nome

def test_validar_nome_colapsa_espacos():
    assert senhas.validar_nome("  Ana   Maria  Silva ") == "Ana Maria Silva"


@pytest.mark.parametrize("invalido", ["", "   ", "A", "x" * 121])
def test_validar_nome_recusa(invalido):
    with pytest.raises(CadastroError):
        senhas.validar_nome(invalido)


# ------------------------------------------------------------------- senha

def test_validar_senha_aceita_valida():
    assert senhas.validar_senha(SENHA_OK) is None


@pytest.mark.parametrize(
    "fraca, motivo",
    [
        ("abc1", "curta"),
        ("", "vazia"),
        ("senhasenha", "sem número"),
        ("12345678", "sem letra"),
        ("a1" + "x" * senhas.MAX_SENHA, "longa demais"),
    ],
)
def test_validar_senha_recusa_fraca(fraca, motivo):
    with pytest.raises(CadastroError):
        senhas.validar_senha(fraca)


def test_validar_senha_aceita_exatamente_no_minimo():
    no_limite = "a" * (senhas.MIN_SENHA - 1) + "1"
    assert len(no_limite) == senhas.MIN_SENHA
    assert senhas.validar_senha(no_limite) is None


# -------------------------------------------------------------- hash/confere

def test_hash_confere_com_a_propria_senha():
    assert senhas.conferir(SENHA_OK, senhas.gerar_hash(SENHA_OK)) is True


def test_hash_nao_confere_com_senha_errada():
    assert senhas.conferir("outra-senha-9", senhas.gerar_hash(SENHA_OK)) is False


def test_hash_nunca_guarda_a_senha_em_claro():
    hash_ = senhas.gerar_hash(SENHA_OK)
    assert SENHA_OK not in hash_
    assert hash_.startswith("$argon2id$")


def test_mesma_senha_gera_hashes_diferentes():
    """Salt aleatório por hash: duas contas com a mesma senha não podem ser
    identificáveis por terem o mesmo hash no banco."""
    assert senhas.gerar_hash(SENHA_OK) != senhas.gerar_hash(SENHA_OK)


@pytest.mark.parametrize("lixo", ["", "nao-e-um-hash", "$argon2id$corrompido", "$2b$12$falso"])
def test_conferir_com_hash_invalido_nega_sem_explodir(lixo):
    """Registro ilegível resolve para 'acesso negado', não para exceção — é
    quem decide um login que chama isto."""
    assert senhas.conferir(SENHA_OK, lixo) is False


def test_senha_longa_e_conferida_por_inteiro():
    """Regressão da razão de não usarmos bcrypt.

    O bcrypt trunca em 72 bytes: estas duas senhas, idênticas até o byte 72,
    teriam o mesmo hash e qualquer uma abriria a conta da outra. Com Argon2id
    a diferença no fim da senha é respeitada.
    """
    base = "z" * 72
    senha = base + "final-verdadeiro-1"
    parecida = base + "final-diferente-2"

    hash_ = senhas.gerar_hash(senha)
    assert senhas.conferir(senha, hash_) is True
    assert senhas.conferir(parecida, hash_) is False


# ----------------------------------------------------------------- rehash

def test_hash_novo_nao_precisa_de_rehash():
    assert senhas.precisa_rehash(senhas.gerar_hash(SENHA_OK)) is False


def test_hash_com_parametros_fracos_pede_rehash():
    """Simula um hash gravado antes de endurecermos o custo do Argon2."""
    from argon2 import PasswordHasher

    antigo = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(SENHA_OK)
    assert senhas.precisa_rehash(antigo) is True


def test_hash_ilegivel_pede_rehash():
    assert senhas.precisa_rehash("nao-e-um-hash") is True


# ------------------------------------------------------------- hash dummy

def test_hash_dummy_e_estavel_no_processo():
    assert senhas.hash_dummy() == senhas.hash_dummy()


def test_hash_dummy_nao_confere_com_nada_util():
    """Ele existe só para gastar o mesmo tempo de um login real quando o
    e-mail não existe — não pode abrir porta nenhuma."""
    assert senhas.conferir(SENHA_OK, senhas.hash_dummy()) is False
    assert senhas.conferir("", senhas.hash_dummy()) is False


# ------------------------------------------------------- senha temporária

def test_senha_temporaria_passa_na_propria_validacao():
    """Uma senha gerada pelo sistema que o próprio sistema recusasse na troca
    seria uma armadilha para quem já está sem acesso."""
    for _ in range(20):
        assert senhas.validar_senha(senhas.gerar_senha_temporaria()) is None


def test_senha_temporaria_e_diferente_a_cada_chamada():
    geradas = {senhas.gerar_senha_temporaria() for _ in range(50)}
    assert len(geradas) == 50


def test_senha_temporaria_evita_caracteres_ambiguos():
    """Ela é copiada à mão do painel do admin: 0/O e 1/l/I viram suporte."""
    ambiguos = set("0O1lI")
    for _ in range(50):
        assert not (set(senhas.gerar_senha_temporaria()) & ambiguos)
