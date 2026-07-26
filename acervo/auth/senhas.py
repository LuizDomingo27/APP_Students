"""Regras puras de credencial — hash de senha, validação e normalização.

Nada aqui toca banco, arquivo ou Streamlit: é tudo função de entrada/saída,
o que permite testar a parte mais sensível do sistema sem subir nada.

Sobre o algoritmo: Argon2id, vencedor da Password Hashing Competition e
primeira recomendação do OWASP. Diferente do bcrypt, ele é *memory-hard* —
exige dezenas de MB por tentativa, e memória é o recurso que GPU e ASIC não
conseguem paralelizar barato. Como efeito colateral bem-vindo, o Argon2 não
tem o truncamento silencioso em 72 bytes do bcrypt, então senhas longas são
conferidas por inteiro (há um teste que fixa esse comportamento).
"""
import re
import secrets
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError, VerifyMismatchError

from acervo.core.exceptions import CadastroError

# Piso recomendado pelo OWASP para Argon2id (m=19 MiB, t=2, p=1). O padrão da
# biblioteca é 64 MiB, que multiplicaria por três o pico de memória de cada
# login — caro demais para o host modesto onde o app roda. Subir estes números
# no futuro é seguro: `precisa_rehash` faz os hashes antigos se atualizarem
# sozinhos no próximo login de cada pessoa.
_TEMPO = 2
_MEMORIA_KIB = 19456
_PARALELISMO = 1

_hasher = PasswordHasher(
    time_cost=_TEMPO,
    memory_cost=_MEMORIA_KIB,
    parallelism=_PARALELISMO,
)

MIN_SENHA = 8
# Sem teto real (o Argon2 não trunca), mas um limite de sanidade impede que
# alguém cole um arquivo inteiro no campo e faça o servidor hashear aquilo.
MAX_SENHA = 1024
MAX_EMAIL = 254

# Validação deliberadamente frouxa: a lista de e-mails válidos pelo RFC é
# absurda e uma regex "esperta" só serve para rejeitar endereço legítimo de
# gente real. Isto pega erro de digitação grosseiro; o resto é com o admin.
_FORMATO_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Alfabeto sem caracteres ambíguos (0/O, 1/l/I) — a senha temporária é lida em
# voz alta ou copiada à mão do painel do admin para quem perdeu o acesso.
_ALFABETO_TEMPORARIA = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
_TAMANHO_TEMPORARIA = 12

_hash_dummy: Optional[str] = None


def normalizar_email(email: str) -> str:
    """Forma canônica do e-mail: sem espaços em volta e em minúsculas.

    A normalização é o que faz o UNIQUE do banco valer de verdade — Postgres
    compara texto com sensibilidade a maiúsculas, então sem isto "Ana@x.com"
    e "ana@x.com" virariam duas contas para a mesma pessoa.
    """
    limpo = (email or "").strip().lower()
    if not limpo:
        raise CadastroError("Informe o e-mail.")
    if len(limpo) > MAX_EMAIL:
        raise CadastroError(f"E-mail longo demais (máximo {MAX_EMAIL} caracteres).")
    if not _FORMATO_EMAIL.match(limpo):
        raise CadastroError(f"'{email.strip()}' não parece um e-mail válido.")
    return limpo


def validar_nome(nome: str) -> str:
    """Nome de exibição, sem espaços duplicados."""
    limpo = " ".join((nome or "").split())
    if len(limpo) < 2:
        raise CadastroError("Informe seu nome (ao menos 2 caracteres).")
    if len(limpo) > 120:
        raise CadastroError("Nome longo demais (máximo 120 caracteres).")
    return limpo


def validar_senha(senha: str) -> None:
    """Recusa senhas fracas. Silêncio significa aprovada.

    Regra modesta de propósito (tamanho + variedade mínima): exigências
    barrocas de símbolo e maiúscula empurram as pessoas para "Senha@123" e
    para o post-it no monitor. O que protege de verdade aqui é o Argon2id.
    """
    senha = senha or ""
    if len(senha) < MIN_SENHA:
        raise CadastroError(f"A senha precisa ter ao menos {MIN_SENHA} caracteres.")
    if len(senha) > MAX_SENHA:
        raise CadastroError(f"Senha longa demais (máximo {MAX_SENHA} caracteres).")
    if not any(c.isalpha() for c in senha):
        raise CadastroError("A senha precisa ter ao menos uma letra.")
    if not any(c.isdigit() for c in senha):
        raise CadastroError("A senha precisa ter ao menos um número.")


def gerar_hash(senha: str) -> str:
    """Hash Argon2id da senha (o salt vai embutido na própria string)."""
    return _hasher.hash(senha)


def conferir(senha: str, hash_: str) -> bool:
    """True se a senha corresponde ao hash. Nunca levanta exceção.

    Hash corrompido ou em formato desconhecido é tratado como "não confere":
    quem chama está decidindo um login, e a resposta segura para um registro
    ilegível é negar o acesso, não explodir na cara do usuário.
    """
    try:
        return _hasher.verify(hash_, senha)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Argon2Error:
        return False


def precisa_rehash(hash_: str) -> bool:
    """True se o hash foi gerado com parâmetros mais fracos que os atuais.

    Permite endurecer o custo do Argon2 sem migração e sem obrigar ninguém a
    trocar de senha: no login seguinte, o serviço regrava o hash atualizado.
    """
    try:
        return _hasher.check_needs_rehash(hash_)
    except (InvalidHashError, Argon2Error):
        return True


def hash_dummy() -> str:
    """Hash descartável para conferir contra quando o e-mail não existe.

    Sem isto, um login com e-mail inexistente responderia na hora, e um com
    e-mail real levaria os ~40 ms do Argon2 — diferença suficiente para
    alguém mapear, por cronômetro, quem tem conta no sistema. Gastando o
    mesmo tempo nos dois casos, o oráculo desaparece.

    Calculado uma vez por processo e a partir dos parâmetros correntes, para
    que o custo continue idêntico ao de um login real se eles mudarem.
    """
    global _hash_dummy
    if _hash_dummy is None:
        _hash_dummy = _hasher.hash(secrets.token_urlsafe(16))
    return _hash_dummy


def gerar_senha_temporaria() -> str:
    """Senha aleatória para o admin repassar a quem perdeu o acesso.

    Sempre sai válida perante `validar_senha` — uma senha temporária que o
    próprio sistema recusasse na hora da troca seria uma armadilha.
    """
    while True:
        senha = "".join(secrets.choice(_ALFABETO_TEMPORARIA) for _ in range(_TAMANHO_TEMPORARIA))
        if any(c.isalpha() for c in senha) and any(c.isdigit() for c in senha):
            return senha
