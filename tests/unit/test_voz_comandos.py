"""Testes da gramática de voz (acervo/voz/comandos.py) — puros, sem microfone.

Três coisas importam aqui, nesta ordem:

1. **O que a frase vira.** Cada comando do vocabulário, dito de mais de um
   jeito, tem que chegar no mesmo `Comando`.
2. **O que a frase *não* pode virar.** Um assistente que chuta é pior que um
   que diz "não entendi" — os testes de não-reconhecimento e de conflito
   entre regras existem para isso.
3. **Que a tela de ajuda não mente.** Todo exemplo mostrado ao usuário é
   interpretado aqui; exemplo quebrado vira teste vermelho.
"""
import pytest

from acervo.voz import comandos as cmd
from acervo.voz.comandos import escolher_opcao, interpretar, normalizar


def _acao(frase: str):
    comando = interpretar(frase)
    return None if comando is None else (comando.acao, comando.valor)


# ------------------------------------------------------------- normalização

def test_normalizar_tira_acento_caixa_e_pontuacao():
    assert normalizar("  Modo   CÓDIGO! ") == "modo codigo"
    assert normalizar("Regressão, linear.") == "regressao linear"


def test_normalizar_frase_vazia():
    assert normalizar("") == ""
    assert normalizar("   ") == ""


# ---------------------------------------------------------------- navegação

@pytest.mark.parametrize("frase", [
    "ir para o dashboard",
    "vai pro painel",
    "abrir dashboard",
    "me mostra as estatísticas",
    "dashboard",
    "visão geral",
])
def test_navegar_para_o_dashboard(frase):
    assert _acao(frase) == (cmd.NAVEGAR, cmd.PAGINA_DASHBOARD)


@pytest.mark.parametrize("frase,pagina", [
    ("voltar para a busca", cmd.PAGINA_BUSCA),
    ("início", cmd.PAGINA_BUSCA),
    ("abrir adicionar", cmd.PAGINA_ADICIONAR),
    ("ir para upload", cmd.PAGINA_ADICIONAR),
    ("usuários", cmd.PAGINA_USUARIOS),
    ("tela de usuários", cmd.PAGINA_USUARIOS),
    ("gerenciar usuários", cmd.PAGINA_USUARIOS),
])
def test_navegar_para_as_demais_paginas(frase, pagina):
    assert _acao(frase) == (cmd.NAVEGAR, pagina)


# -------------------------------------------------------------------- busca

@pytest.mark.parametrize("frase", [
    "buscar regressão linear",
    "pesquisar regressão linear",
    "procure regressão linear",
    "buscar sobre regressão linear",
    "encontre regressão linear",
])
def test_buscar_extrai_o_termo(frase):
    assert _acao(frase) == (cmd.BUSCAR, "regressão linear")


def test_termo_de_busca_preserva_acento_e_caixa_do_original():
    """O Postgres acha os dois; quem lê a caixa de busca vê um só."""
    assert _acao("procurar por LEFT JOIN") == (cmd.BUSCAR, "LEFT JOIN")
    assert _acao("buscar função de janela") == (cmd.BUSCAR, "função de janela")


def test_verbo_de_busca_sem_termo_nao_e_busca():
    """"buscar" sozinho é a página, não uma busca pelo vazio."""
    assert _acao("buscar") == (cmd.NAVEGAR, cmd.PAGINA_BUSCA)


def test_limpar_busca_e_filtros_sao_comandos_distintos():
    assert _acao("limpar a busca") == (cmd.LIMPAR_BUSCA, None)
    assert _acao("apagar o termo") == (cmd.LIMPAR_BUSCA, None)
    assert _acao("limpar filtros") == (cmd.LIMPAR_FILTROS, None)
    assert _acao("todas as categorias") == (cmd.LIMPAR_FILTROS, None)
    assert _acao("limpar tudo") == (cmd.LIMPAR_TUDO, None)


# --------------------------------------------------------------------- modo

@pytest.mark.parametrize("frase", ["modo código", "modo de código", "buscar em código"])
def test_modo_codigo(frase):
    assert _acao(frase) == (cmd.MODO, cmd.MODO_CODIGO)


@pytest.mark.parametrize("frase", ["modo texto", "alternar para texto", "modo conceito"])
def test_modo_texto(frase):
    assert _acao(frase) == (cmd.MODO, cmd.MODO_TEXTO)


# ----------------------------------------------------------------- filtros

def test_filtro_de_categoria_devolve_o_valor_cru():
    """Quais categorias existem é pergunta para o banco, não para a gramática."""
    assert _acao("categoria Databricks") == (cmd.CATEGORIA, "Databricks")
    assert _acao("filtrar por categoria Machine Learning") == (cmd.CATEGORIA, "Machine Learning")


def test_filtro_de_linguagem_e_conteudo():
    assert _acao("linguagem python") == (cmd.LINGUAGEM, "python")
    assert _acao("conteúdo aula 3") == (cmd.CONTEUDO, "aula 3")
    assert _acao("aula 3") == (cmd.CONTEUDO, "aula 3")


def test_filtro_sem_valor_nao_vira_comando():
    assert interpretar("categoria") is None
    assert interpretar("linguagem") is None


# -------------------------------------------------------------- paginação

@pytest.mark.parametrize("frase", ["próxima página", "próxima", "avançar", "mais resultados"])
def test_proxima_pagina(frase):
    assert _acao(frase) == (cmd.PAGINA, cmd.PROXIMA)


@pytest.mark.parametrize("frase", ["página anterior", "anterior", "resultados anteriores"])
def test_pagina_anterior(frase):
    assert _acao(frase) == (cmd.PAGINA, cmd.ANTERIOR)


def test_pagina_por_numero_falado_ou_escrito():
    assert _acao("página 3") == (cmd.PAGINA, "3")
    assert _acao("página três") == (cmd.PAGINA, "3")
    assert _acao("primeira página") == (cmd.PAGINA, "1")


# ---------------------------------------------------------- abrir resultado

@pytest.mark.parametrize("frase,posicao", [
    ("abrir o segundo resultado", "2"),
    ("abre o primeiro", "1"),
    ("abrir resultado 4", "4"),
    ("terceiro resultado", "3"),
    ("abrir o último resultado", "-1"),
])
def test_abrir_resultado_por_ordinal_ou_numero(frase, posicao):
    assert _acao(frase) == (cmd.ABRIR, posicao)


def test_numero_solto_nao_abre_nada():
    """Ruído da sala não pode abrir arquivo: exige verbo ou a palavra 'resultado'."""
    assert interpretar("três") is None
    assert interpretar("2") is None


# --------------------------------------------------------------- conta

def test_trocar_senha():
    assert _acao("trocar minha senha") == (cmd.TROCAR_SENHA, None)
    assert _acao("quero alterar a senha") == (cmd.TROCAR_SENHA, None)


def test_buscar_pela_palavra_senha_continua_sendo_busca():
    """O verbo tem que vir antes de 'senha' — senão a busca vira troca de senha."""
    assert _acao("buscar senha forte") == (cmd.BUSCAR, "senha forte")


def test_sair_exige_frase_inteira():
    """"sair" solto aparece em qualquer conversa perto do microfone."""
    assert _acao("encerrar sessão") == (cmd.SAIR, None)
    assert _acao("sair do sistema") == (cmd.SAIR, None)
    assert interpretar("sair") is None
    assert interpretar("tchau") is None


# ---------------------------------------------------------------- ativação

@pytest.mark.parametrize("frase", [
    "assistente, ir para o dashboard",
    "ok assistente buscar regressão",
    "computador próxima página",
])
def test_palavra_de_ativacao_e_reconhecida_e_descartada(frase):
    assert cmd.tem_ativacao(frase) is True
    assert interpretar(frase) is not None


def test_ativacao_com_cortesia_no_meio():
    assert _acao("assistente, por favor abrir o dashboard") == (
        cmd.NAVEGAR, cmd.PAGINA_DASHBOARD
    )


def test_frase_sem_ativacao():
    assert cmd.tem_ativacao("ir para o dashboard") is False
    assert cmd.tem_ativacao("") is False


def test_ativacao_sozinha_nao_e_comando():
    assert interpretar("assistente") is None


# ------------------------------------------------------- o que não entendi

@pytest.mark.parametrize("frase", [
    "",
    "   ",
    "então eu falei pra ela que não dava",
    "hoje o tempo está bom",
    "xyzzy",
])
def test_frase_fora_do_vocabulario_devolve_none(frase):
    """Preferimos "não entendi" a chutar — quem usa voz não desfaz rápido."""
    assert interpretar(frase) is None


# --------------------------------------------------- casar com o que existe

CATEGORIAS = ("Databricks · Módulo 1", "Machine Learning", "SQL Avançado", "Python")


def test_escolher_opcao_exata_e_sem_acento():
    assert escolher_opcao("Machine Learning", CATEGORIAS) == "Machine Learning"
    assert escolher_opcao("sql avancado", CATEGORIAS) == "SQL Avançado"


def test_escolher_opcao_por_prefixo_e_por_palavras():
    assert escolher_opcao("databricks", CATEGORIAS) == "Databricks · Módulo 1"
    assert escolher_opcao("machine", CATEGORIAS) == "Machine Learning"


def test_escolher_opcao_tolera_erro_do_reconhecimento():
    """"data brics" é o que o navegador devolve para "Databricks"."""
    assert escolher_opcao("databriks", CATEGORIAS) == "Databricks · Módulo 1"


def test_escolher_opcao_sem_parecido_devolve_none():
    assert escolher_opcao("geografia", CATEGORIAS) is None
    assert escolher_opcao("", CATEGORIAS) is None
    assert escolher_opcao("python", ()) is None


# ------------------------------------------------------------ tela de ajuda

@pytest.mark.parametrize(
    "exemplo",
    [frase for _, frases in cmd.EXEMPLOS for frase in frases],
)
def test_todo_exemplo_da_tela_de_ajuda_e_interpretavel(exemplo):
    assert interpretar(exemplo) is not None, f"a ajuda promete “{exemplo}” e ele não funciona"


def test_todo_comando_tem_descricao_para_confirmar_na_tela():
    for _, frases in cmd.EXEMPLOS:
        for frase in frases:
            comando = interpretar(frase)
            assert comando.descricao, f"“{frase}” executa sem dizer o que fez"
