"""Cadastro, login e troca de senha.

Este módulo decide quem entra no acervo, então duas regras valem em tudo o
que está aqui:

1. **A tela de login não pode virar um oráculo de e-mails cadastrados.**
   E-mail inexistente e senha errada produzem exatamente a mesma mensagem e
   consomem o mesmo tempo (ver `senhas.hash_dummy`). O motivo real da recusa
   — conta pendente, recusada ou bloqueada — só é revelado *depois* de a
   senha ser conferida como correta; caso contrário, a própria mensagem
   "aguardando aprovação" denunciaria quem tem cadastro.

2. **Credencial não sai daqui.** O hash é lido do repositório, usado e
   descartado dentro da função; o `Usuario` devolvido nunca o carrega.
"""
import logging
from typing import Optional

from acervo.auth import senhas
from acervo.core.exceptions import AutenticacaoError, CadastroError
from acervo.core.models import Usuario
from acervo.persistence.db import cursor
from acervo.persistence.repository import UsuarioRepository

logger = logging.getLogger("acervo.auth")

# Mensagem única para "não existe" e "senha errada" — ver regra 1 acima.
_CREDENCIAL_INVALIDA = "E-mail ou senha incorretos."

_MOTIVO_SEM_ACESSO = {
    "pendente": (
        "Seu cadastro foi recebido e aguarda aprovação de um administrador. "
        "Tente novamente mais tarde."
    ),
    "recusado": "Seu cadastro não foi aprovado. Procure um administrador.",
    "bloqueado": "Seu acesso está bloqueado. Procure um administrador.",
}


def cadastrar(
    nome: str,
    email: str,
    senha: str,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Cria uma conta nova, sempre pendente de aprovação.

    Ao contrário do login, aqui a mensagem *diz* que o e-mail já está em uso.
    É uma exposição consciente: sem envio de e-mail de confirmação, fingir
    sucesso deixaria quem já tem conta esperando para sempre por uma
    aprovação que nunca chegaria. O dano é pequeno (descobrir que um endereço
    tem cadastro) perto da confusão que a alternativa causaria.
    """
    nome = senhas.validar_nome(nome)
    email = senhas.normalizar_email(email)
    senhas.validar_senha(senha)

    repo = usuarios_repo or UsuarioRepository(schema)
    with cursor() as cur:
        usuario = repo.criar(cur, nome, email, senhas.gerar_hash(senha))

    if usuario is None:
        raise CadastroError(
            "Já existe uma conta com este e-mail. Use a aba 'Entrar' ou "
            "procure um administrador se você perdeu o acesso."
        )

    logger.info("Cadastro criado, pendente de aprovação: %s", email)
    return usuario


def autenticar(
    email: str,
    senha: str,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Confere as credenciais e devolve o usuário, ou levanta AutenticacaoError."""
    try:
        email = senhas.normalizar_email(email)
    except CadastroError:
        # E-mail malformado nunca poderia estar no banco (todos são
        # normalizados na gravação). Responder o mesmo "credencial inválida"
        # evita que o formato do erro diferencie "não existe" de "inválido".
        raise AutenticacaoError(_CREDENCIAL_INVALIDA) from None

    repo = usuarios_repo or UsuarioRepository(schema)
    with cursor() as cur:
        encontrado = repo.buscar_por_email(cur, email)

        if encontrado is None:
            # Gasta o mesmo tempo de um login real antes de negar: sem isto,
            # o relógio revelaria quais e-mails têm conta.
            senhas.conferir(senha, senhas.hash_dummy())
            logger.info("Login recusado (e-mail sem cadastro): %s", email)
            raise AutenticacaoError(_CREDENCIAL_INVALIDA)

        usuario, senha_hash = encontrado
        if not senhas.conferir(senha, senha_hash):
            logger.info("Login recusado (senha incorreta): %s", email)
            raise AutenticacaoError(_CREDENCIAL_INVALIDA)

        # Daqui para baixo a identidade está provada — só agora é seguro
        # explicar por que a conta não entra.
        if not usuario.tem_acesso:
            logger.info("Login recusado (status=%s): %s", usuario.status, email)
            raise AutenticacaoError(
                _MOTIVO_SEM_ACESSO.get(usuario.status, "Sua conta não tem acesso liberado.")
            )

        if senhas.precisa_rehash(senha_hash):
            # Endurecer os parâmetros do Argon2 no futuro não exige migração
            # nem trocar senha: o hash se atualiza no login seguinte.
            logger.info("Regravando hash com os parâmetros atuais: %s", email)
            repo.atualizar_senha(
                cur, usuario.id, senhas.gerar_hash(senha),
                temporaria=usuario.senha_temporaria,
            )

        repo.registrar_acesso(cur, usuario.id)

    return usuario


def alterar_senha(
    usuario: Usuario,
    senha_atual: str,
    nova_senha: str,
    *,
    schema: str = "acervo",
    usuarios_repo: Optional[UsuarioRepository] = None,
) -> Usuario:
    """Troca a senha do próprio usuário e limpa a marca de senha temporária.

    Exige a senha atual mesmo quando ela é a temporária gerada pelo admin —
    é o que impede que uma sessão esquecida aberta troque a senha e tome a
    conta em definitivo.
    """
    senhas.validar_senha(nova_senha)
    if nova_senha == senha_atual:
        raise CadastroError("A nova senha precisa ser diferente da atual.")

    repo = usuarios_repo or UsuarioRepository(schema)
    with cursor() as cur:
        encontrado = repo.buscar_por_email(cur, usuario.email)
        if encontrado is None:
            raise AutenticacaoError("Conta não encontrada.")

        atual, senha_hash = encontrado
        if not senhas.conferir(senha_atual, senha_hash):
            raise AutenticacaoError("A senha atual está incorreta.")

        repo.atualizar_senha(cur, atual.id, senhas.gerar_hash(nova_senha), temporaria=False)
        atualizado = repo.buscar_por_id(cur, atual.id)

    logger.info("Senha alterada: %s", usuario.email)
    return atualizado
