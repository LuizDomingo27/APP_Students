"""Testes de integração do UsuarioRepository contra o Neon.

Cobrem o que só o banco real prova: unicidade de e-mail sob ON CONFLICT,
as constraints CHECK de papel/status, os carimbos de tempo do servidor e a
ordenação da fila do painel do admin.

Rodam em um schema descartável (fixture `schema_teste`) e são pulados sem
DATABASE_URL configurado.
"""
import pytest

from acervo.core.exceptions import ConexaoBancoError
from acervo.persistence.db import cursor
from acervo.persistence.repository import UsuarioRepository

pytestmark = pytest.mark.integration

HASH_FALSO = "$argon2id$v=19$m=19456,t=2,p=1$hash-de-teste"


@pytest.fixture
def repo(schema_teste):
    return UsuarioRepository(schema_teste)


@pytest.fixture(autouse=True)
def _limpar_usuarios(schema_teste):
    """Cada teste começa com a tabela vazia — eles compartilham o schema da
    sessão, então sem isto um teste veria as contas criadas pelo anterior."""
    yield
    with cursor() as cur:
        cur.execute(f'DELETE FROM "{schema_teste}".usuarios')


def _criar(repo, cur, nome, email, **kwargs):
    return repo.criar(cur, nome, email, HASH_FALSO, **kwargs)


# ------------------------------------------------------------------- criar

def test_criar_nasce_pendente_e_sem_privilegio(repo):
    with cursor() as cur:
        usuario = _criar(repo, cur, "Ana Silva", "ana@exemplo.com")

    assert usuario.id is not None
    assert usuario.status == "pendente"
    assert usuario.papel == "usuario"
    assert usuario.tem_acesso is False
    assert usuario.eh_admin is False
    assert usuario.senha_temporaria is False
    assert usuario.criado_em is not None      # default now() do servidor
    assert usuario.ultimo_acesso is None


def test_criar_com_email_repetido_devolve_none(repo):
    """O segundo cadastro não pode estourar exceção nem sobrescrever o
    primeiro: devolve None para o serviço traduzir em 'e-mail já em uso'."""
    with cursor() as cur:
        primeiro = _criar(repo, cur, "Ana", "ana@exemplo.com")
        segundo = _criar(repo, cur, "Outra Ana", "ana@exemplo.com")

    assert primeiro is not None
    assert segundo is None

    with cursor() as cur:
        assert repo.buscar_por_email(cur, "ana@exemplo.com")[0].nome == "Ana"


def test_criar_admin_aprovado_direto(repo):
    """Caminho do scripts/criar_admin.py — nasce pronto para usar."""
    with cursor() as cur:
        admin = _criar(repo, cur, "Root", "root@exemplo.com", papel="admin", status="aprovado")

    assert admin.eh_admin is True
    assert admin.tem_acesso is True


@pytest.mark.parametrize(
    "campo, valor",
    [("papel", "superusuario"), ("status", "meio-aprovado")],
)
def test_banco_recusa_papel_ou_status_invalido(repo, campo, valor):
    """As CHECK da migração são a última linha de defesa se um bug no
    serviço tentar gravar um estado que não existe na máquina de estados."""
    with pytest.raises(ConexaoBancoError):
        with cursor() as cur:
            _criar(repo, cur, "X", "x@exemplo.com", **{campo: valor})


# ------------------------------------------------------------------ buscar

def test_buscar_por_email_devolve_usuario_e_hash(repo):
    with cursor() as cur:
        _criar(repo, cur, "Ana", "ana@exemplo.com")
        usuario, senha_hash = repo.buscar_por_email(cur, "ana@exemplo.com")

    assert usuario.email == "ana@exemplo.com"
    assert senha_hash == HASH_FALSO


def test_buscar_por_email_inexistente_devolve_none(repo):
    with cursor() as cur:
        assert repo.buscar_por_email(cur, "ninguem@exemplo.com") is None


def test_buscar_por_id(repo):
    with cursor() as cur:
        criado = _criar(repo, cur, "Ana", "ana@exemplo.com")
        assert repo.buscar_por_id(cur, criado.id).email == "ana@exemplo.com"
        assert repo.buscar_por_id(cur, 999_999) is None


# ------------------------------------------------------------------ listar

def test_listar_poe_pendentes_no_topo(repo):
    """A ordem existe para o painel: o que exige decisão aparece primeiro."""
    with cursor() as cur:
        _criar(repo, cur, "Aprovado", "aprovado@exemplo.com", status="aprovado")
        _criar(repo, cur, "Bloqueado", "bloqueado@exemplo.com", status="bloqueado")
        _criar(repo, cur, "Recusado", "recusado@exemplo.com", status="recusado")
        _criar(repo, cur, "Pendente", "pendente@exemplo.com")

        status = [u.status for u in repo.listar(cur)]

    assert status == ["pendente", "aprovado", "bloqueado", "recusado"]


def test_listar_filtra_por_status(repo):
    with cursor() as cur:
        _criar(repo, cur, "Ana", "ana@exemplo.com")
        _criar(repo, cur, "Bia", "bia@exemplo.com", status="aprovado")

        pendentes = repo.listar(cur, status="pendente")

    assert [u.nome for u in pendentes] == ["Ana"]


def test_contar_por_status(repo):
    with cursor() as cur:
        _criar(repo, cur, "Ana", "ana@exemplo.com")
        _criar(repo, cur, "Bia", "bia@exemplo.com")
        _criar(repo, cur, "Caio", "caio@exemplo.com", status="aprovado")

        contagem = repo.contar_por_status(cur)

    assert contagem == {"pendente": 2, "aprovado": 1}


# --------------------------------------------------------------- atualizar

def test_atualizar_status_carimba_quem_decidiu(repo, schema_teste):
    with cursor() as cur:
        admin = _criar(repo, cur, "Admin", "admin@exemplo.com", papel="admin", status="aprovado")
        ana = _criar(repo, cur, "Ana", "ana@exemplo.com")

        assert repo.atualizar_status(cur, ana.id, "aprovado", decidido_por=admin.id) is True

        cur.execute(
            f'SELECT status, decidido_por, decidido_em FROM "{schema_teste}".usuarios WHERE id = %s',
            (ana.id,),
        )
        status, decidido_por, decidido_em = cur.fetchone()

    assert status == "aprovado"
    assert decidido_por == admin.id
    assert decidido_em is not None


def test_atualizar_status_de_id_inexistente_devolve_false(repo):
    with cursor() as cur:
        assert repo.atualizar_status(cur, 999_999, "aprovado", decidido_por=None) is False


def test_bloquear_e_reativar_preservam_o_cadastro(repo):
    """Revogar acesso nunca apaga a linha — o histórico e o e-mail continuam
    ocupados, então a pessoa não volta para a fila recriando o cadastro."""
    with cursor() as cur:
        ana = _criar(repo, cur, "Ana", "ana@exemplo.com", status="aprovado")

        repo.atualizar_status(cur, ana.id, "bloqueado", decidido_por=None)
        assert repo.buscar_por_id(cur, ana.id).tem_acesso is False
        assert _criar(repo, cur, "Ana de novo", "ana@exemplo.com") is None

        repo.atualizar_status(cur, ana.id, "aprovado", decidido_por=None)
        devolvida = repo.buscar_por_id(cur, ana.id)

    assert devolvida.tem_acesso is True
    assert devolvida.nome == "Ana"


def test_atualizar_senha_marca_e_limpa_a_flag_de_temporaria(repo):
    with cursor() as cur:
        ana = _criar(repo, cur, "Ana", "ana@exemplo.com", status="aprovado")

        repo.atualizar_senha(cur, ana.id, "hash-temporario", temporaria=True)
        assert repo.buscar_por_id(cur, ana.id).senha_temporaria is True

        repo.atualizar_senha(cur, ana.id, "hash-escolhido-por-ela")
        recarregada = repo.buscar_por_id(cur, ana.id)
        _, senha_hash = repo.buscar_por_email(cur, "ana@exemplo.com")

    assert recarregada.senha_temporaria is False
    assert senha_hash == "hash-escolhido-por-ela"


def test_atualizar_papel(repo):
    with cursor() as cur:
        ana = _criar(repo, cur, "Ana", "ana@exemplo.com", status="aprovado")
        assert repo.atualizar_papel(cur, ana.id, "admin") is True
        assert repo.buscar_por_id(cur, ana.id).eh_admin is True


def test_registrar_acesso_preenche_ultimo_acesso(repo):
    with cursor() as cur:
        ana = _criar(repo, cur, "Ana", "ana@exemplo.com", status="aprovado")
        assert repo.buscar_por_id(cur, ana.id).ultimo_acesso is None

        repo.registrar_acesso(cur, ana.id)
        assert repo.buscar_por_id(cur, ana.id).ultimo_acesso is not None


# ------------------------------------------------------------ salvaguardas

def test_contar_admins_ativos_ignora_inativos_e_comuns(repo):
    with cursor() as cur:
        _criar(repo, cur, "Admin 1", "a1@exemplo.com", papel="admin", status="aprovado")
        _criar(repo, cur, "Admin 2", "a2@exemplo.com", papel="admin", status="aprovado")
        _criar(repo, cur, "Admin bloqueado", "a3@exemplo.com", papel="admin", status="bloqueado")
        _criar(repo, cur, "Comum", "c@exemplo.com", status="aprovado")

        assert repo.contar_admins_ativos(cur) == 2


def test_contar_admins_ativos_com_excecao(repo):
    """É assim que o serviço pergunta 'se eu tirar este, sobra alguém?'."""
    with cursor() as cur:
        unico = _criar(repo, cur, "Único", "unico@exemplo.com", papel="admin", status="aprovado")

        assert repo.contar_admins_ativos(cur, exceto=unico.id) == 0
        assert repo.contar_admins_ativos(cur, exceto=None) == 1


def test_existe_algum(repo):
    with cursor() as cur:
        assert repo.existe_algum(cur) is False
        _criar(repo, cur, "Ana", "ana@exemplo.com")
        assert repo.existe_algum(cur) is True
