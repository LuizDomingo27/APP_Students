"""Cria (ou promove) o primeiro administrador do acervo.

Existe porque a aprovação de cadastros é feita por um admin, e o primeiro
deles não tem quem o aprove: alguém precisa criá-lo pelo servidor, com acesso
ao `.env`. Depois disso, tudo é feito pelo painel.

Uso:
    python scripts/criar_admin.py --email voce@exemplo.com --nome "Seu Nome"
    python scripts/criar_admin.py --email voce@exemplo.com --redefinir-senha
    python scripts/criar_admin.py --email voce@exemplo.com --schema outro

A senha é pedida no terminal, nunca na linha de comando — argumento de
comando vai para o histórico do shell, para a lista de processos e para
qualquer log de auditoria da máquina.

Idempotente. Se a conta já existir, ela é **promovida** (papel `admin`,
status `aprovado`) em vez de o script falhar, e a senha só é tocada com
`--redefinir-senha`. Rodar duas vezes seguidas não causa dano.
"""
import argparse
import getpass
import logging
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from acervo.auth import senhas
from acervo.core.exceptions import AcervoError, CadastroError
from acervo.persistence.db import cursor
from acervo.persistence.repository import UsuarioRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("acervo.scripts.criar_admin")

_MAX_TENTATIVAS = 3


def _pedir_senha() -> str:
    """Lê a senha do terminal, com confirmação, sem eco na tela.

    Aborta se a entrada não for um terminal: fora dele o `getpass` cai para
    leitura comum e a senha apareceria na tela (e no log de quem estivesse
    capturando a saída).
    """
    if not sys.stdin.isatty():
        raise SystemExit(
            "Este script precisa de um terminal interativo para ler a senha com segurança."
        )

    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        senha = getpass.getpass("Senha do administrador: ")
        try:
            senhas.validar_senha(senha)
        except CadastroError as e:
            print(f"  {e}")
            continue

        if senha != getpass.getpass("Repita a senha: "):
            print("  As senhas não conferem.")
            continue

        return senha

    raise SystemExit(f"Senha não definida após {_MAX_TENTATIVAS} tentativas.")


def criar_admin(
    email: str,
    nome: str = "",
    *,
    redefinir_senha: bool = False,
    schema: str = "acervo",
) -> None:
    email = senhas.normalizar_email(email)
    repo = UsuarioRepository(schema)

    with cursor() as cur:
        encontrado = repo.buscar_por_email(cur, email)

    if encontrado is None:
        if not nome:
            raise SystemExit(
                f"Não existe conta com o e-mail {email}. "
                "Para criá-la, informe também --nome \"Seu Nome\"."
            )
        nome = senhas.validar_nome(nome)
        senha = _pedir_senha()

        with cursor() as cur:
            usuario = repo.criar(
                cur, nome, email, senhas.gerar_hash(senha),
                papel="admin", status="aprovado",
            )

        if usuario is None:
            # Alguém cadastrou este e-mail entre a consulta e o INSERT.
            raise SystemExit(
                f"A conta {email} foi criada por outra via durante a execução. "
                "Rode o comando de novo para promovê-la."
            )

        print(f"Administrador criado: {usuario.nome} <{usuario.email}> (id {usuario.id})")
        return

    usuario, _ = encontrado
    mudancas = []

    senha = _pedir_senha() if redefinir_senha else None

    with cursor() as cur:
        if not usuario.eh_admin:
            repo.atualizar_papel(cur, usuario.id, "admin")
            mudancas.append(f"papel {usuario.papel} -> admin")
        if not usuario.tem_acesso:
            # decidido_por fica nulo de propósito: quem decidiu foi o console
            # do servidor, não um administrador do painel.
            repo.atualizar_status(cur, usuario.id, "aprovado", decidido_por=None)
            mudancas.append(f"status {usuario.status} -> aprovado")
        if senha is not None:
            repo.atualizar_senha(cur, usuario.id, senhas.gerar_hash(senha), temporaria=False)
            mudancas.append("senha redefinida")

    if mudancas:
        print(f"Conta {usuario.email} atualizada: {', '.join(mudancas)}.")
    else:
        print(f"Conta {usuario.email} já é administradora e está aprovada — nada a fazer.")


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(
        description="Cria ou promove um administrador do acervo (a senha é pedida no terminal).",
    )
    argparser.add_argument("--email", required=True)
    argparser.add_argument("--nome", default="", help="Obrigatório apenas ao criar uma conta nova.")
    argparser.add_argument(
        "--redefinir-senha", action="store_true",
        help="Define uma senha nova para uma conta que já existe.",
    )
    argparser.add_argument("--schema", default="acervo")
    args = argparser.parse_args()

    try:
        criar_admin(
            args.email,
            args.nome,
            redefinir_senha=args.redefinir_senha,
            schema=args.schema,
        )
    except AcervoError as e:
        logger.error("Falhou: %s", e)
        raise SystemExit(1) from e
