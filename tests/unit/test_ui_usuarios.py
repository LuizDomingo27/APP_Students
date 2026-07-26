"""Testes dos pedaços puros do painel de usuários (app/paginas/usuarios.py).

O que dá para testar sem subir Streamlit é o que decide *o que aparece*: em
que aba cada cadastro cai e o que o cartão diz sobre a pessoa. As ações em si
são só chamadas ao `admin_service`, que tem os próprios testes.
"""
from datetime import datetime

from acervo.core.models import Usuario
from app.paginas.usuarios import agrupar_por_situacao, rotulo_aba


def _usuario(**kwargs) -> Usuario:
    campos = {
        "id": 1, "nome": "Ana Silva", "email": "ana@exemplo.com",
        "papel": "usuario", "status": "aprovado",
    }
    return Usuario(**{**campos, **kwargs})


def test_rotulo_da_aba_mostra_contagem_so_quando_ha_algo():
    assert rotulo_aba("Pendentes", 3) == "Pendentes (3)"
    assert rotulo_aba("Pendentes", 0) == "Pendentes"


def test_agrupar_separa_as_tres_abas():
    pendente = _usuario(id=1, status="pendente")
    ativo = _usuario(id=2, status="aprovado")
    recusado = _usuario(id=3, status="recusado")
    bloqueado = _usuario(id=4, status="bloqueado")

    pendentes, ativos, inativos = agrupar_por_situacao(
        [pendente, ativo, recusado, bloqueado]
    )

    assert pendentes == [pendente]
    assert ativos == [ativo]
    # recusado e bloqueado dividem a mesma aba, na ordem em que vieram
    assert inativos == [recusado, bloqueado]


def test_agrupar_sem_ninguem():
    assert agrupar_por_situacao([]) == ([], [], [])


def test_cartao_identifica_status_papel_e_datas():
    from app.paginas.usuarios import _identificacao

    html_cartao = _identificacao(
        _usuario(
            papel="admin",
            senha_temporaria=True,
            criado_em=datetime(2026, 3, 9),
            ultimo_acesso=None,
        ),
        eu=True,
    )

    assert "ana@exemplo.com" in html_cartao
    assert "ativo" in html_cartao
    assert "admin" in html_cartao
    assert "senha temporária" in html_cartao
    assert "você" in html_cartao
    assert "09/03/2026" in html_cartao
    assert "último acesso: —" in html_cartao


def test_cartao_escapa_o_que_a_pessoa_digitou_no_cadastro():
    from app.paginas.usuarios import _identificacao

    html_cartao = _identificacao(_usuario(nome="<script>alert(1)</script>"), eu=False)

    assert "<script>" not in html_cartao
    assert "&lt;script&gt;" in html_cartao
