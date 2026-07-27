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
    "Luiz, ir para o dashboard",
    "oi Luiz, buscar regressão",
    "Luís próxima página",
    "ok Luiz, modo código",
])
def test_o_nome_e_reconhecido_e_descartado_antes_das_regras(frase):
    assert cmd.tem_ativacao(frase) is True
    assert interpretar(frase) is not None


def test_variantes_que_o_reconhecimento_devolve_para_o_mesmo_nome():
    """"Luís", "Luiza", "Ruiz" — a grafia é escolha do navegador, não da pessoa."""
    for variante in ("Luiz", "Luís", "Luiza", "Ruiz", "lui"):
        assert cmd.tem_ativacao(f"{variante}, próxima página") is True


def test_cortesia_entre_o_nome_e_o_comando():
    assert _acao("Luiz, por favor abrir o dashboard") == (
        cmd.NAVEGAR, cmd.PAGINA_DASHBOARD
    )
    assert _acao("oi Luiz, me faz uma busca por regressão") == (
        cmd.BUSCAR, "regressão"
    )


def test_frase_sem_o_nome():
    assert cmd.tem_ativacao("ir para o dashboard") is False
    assert cmd.tem_ativacao("") is False
    assert cmd.tem_ativacao("o assistente já foi") is False


def test_o_nome_sozinho_e_uma_saudacao_nao_um_comando():
    for chamado in ("Luiz", "oi Luiz", "olá Luiz", "Luiz?"):
        comando = interpretar(chamado)
        assert comando is not None and comando.acao == cmd.SAUDACAO
        assert comando.descricao == cmd.SAUDACAO_RESPOSTA


# ------------------------------------------------- perguntas em voz natural

@pytest.mark.parametrize("frase,termo", [
    ("explique como fazer uma procedure usando SQL Server", "procedure SQL Server"),
    ("como fazer um group by usando pandas", "group by pandas"),
    ("o que é uma janela de tempo", "janela tempo"),
    ("me explica o que é regressão linear", "regressão linear"),
    ("para que serve o cross join", "cross join"),
    ("exemplo de list comprehension em python", "list comprehension python"),
])
def test_pergunta_natural_vira_busca_pelo_conteudo(frase, termo):
    """A estrutura da pergunta cai; o AND do full-text não sobrevive a ela."""
    assert _acao(frase) == (cmd.BUSCAR, termo)


def test_pergunta_preserva_acento_e_caixa_do_que_sobrou():
    assert cmd.termo_de_busca("Luiz, explique o que é uma FUNÇÃO de janela") == (
        "FUNÇÃO janela"
    )


def test_pergunta_que_e_so_estrutura_nao_vira_termo():
    assert cmd.termo_de_busca("me explica isso aí então") == ""
    assert cmd.termo_de_busca("") == ""


def test_pergunta_nao_rouba_a_navegacao_pelo_nome_da_pagina():
    """"dashboard" abre a página; "o que é um dashboard" é sobre o assunto."""
    assert _acao("dashboard") == (cmd.NAVEGAR, cmd.PAGINA_DASHBOARD)
    assert _acao("o que é um dashboard") == (cmd.BUSCAR, "dashboard")


def test_termos_essenciais_derrubam_as_particulas_curtas():
    """Segunda tentativa da busca: "by" isolado nunca casa com `df.groupby`."""
    assert cmd.termos_essenciais("group by pandas") == "group pandas"
    assert cmd.termos_essenciais("regressão linear") == "regressão linear"
    assert cmd.termos_essenciais("") == ""


# ------------------------------------------------------- vocabulário aberto

def test_interpretar_livre_manda_o_desconhecido_para_a_busca():
    assert interpretar("materialized view no postgres") is None
    comando = cmd.interpretar_livre("materialized view no postgres")
    assert (comando.acao, comando.valor) == (cmd.BUSCAR, "materialized view postgres")


def test_interpretar_livre_nao_atropela_os_comandos():
    """Vocabulário aberto vale para o que sobra, não para o que já é comando."""
    for frase in ("próxima página", "modo código", "limpar tudo", "encerrar sessão"):
        assert cmd.interpretar_livre(frase) == interpretar(frase)


def test_interpretar_livre_sem_conteudo_nenhum_desiste():
    assert cmd.interpretar_livre("é então né") is None
    assert cmd.interpretar_livre("") is None


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
