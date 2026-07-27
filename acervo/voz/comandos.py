"""Gramática do assistente de voz — uma frase em português vira um `Comando`.

Camada pura: não conhece Streamlit, microfone nem banco. Recebe o texto que o
navegador transcreveu e decide *o que fazer*; quem faz é `app.voz`. É essa
separação que torna o assistente testável — todo o vocabulário abaixo é
exercitado por `tests/unit/test_voz.py`, sem subir servidor nem microfone.

Duas decisões que atravessam o arquivo, porque reconhecimento de fala erra e
um erro aqui executa a ação errada:

* **Nada acontece sem o nome.** O assistente atende por "Luiz" e ignora toda
  frase que não o chame — em qualquer modo, inclusive digitando. É o que
  torna seguro deixar o microfone aberto: a conversa da sala não vira
  comando. "Luiz" sozinho não é comando nenhum, é uma saudação, e responder a
  ela é a forma mais barata de a pessoa descobrir que foi ouvida.
* **Vocabulário fechado para *agir*, aberto para *procurar*.** Nenhuma frase
  desconhecida vira ação: `interpretar` devolve `None` em vez de chutar entre
  navegar e limpar, porque quem depende de voz não desfaz rápido. Mas parar
  aí faria o assistente recusar justamente o que o acervo tem de melhor — o
  assunto. Então `interpretar_livre` manda a sobra para a busca, onde o pior
  caso é uma lista vazia. As duas portas existem, e cada chamador escolhe.
* **Pergunta falada não é palavra-chave.** "explique como fazer uma procedure
  usando SQL Server" tem cinco palavras de estrutura e três de conteúdo; como
  o full-text faz AND de tudo, mandar a frase inteira devolve zero mesmo com
  o material no banco. `termo_de_busca` derruba a estrutura antes.
* **Ação que tira algo exige frase longa.** "sair" sozinho aparece em qualquer
  conversa perto do microfone; encerrar sessão só acontece com "encerrar
  sessão" ou "sair do sistema".

Ordem das regras importa: `buscar dashboard` é uma busca pelo termo
"dashboard", não uma navegação. As regras mais específicas vêm primeiro e a
primeira que casa vence.
"""
import difflib
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# ------------------------------------------------------------------- ações
# Constantes em vez de strings soltas: `app.voz` compara contra elas e um
# erro de digitação vira NameError na hora, não um comando que nunca executa.

NAVEGAR = "navegar"
BUSCAR = "buscar"
LIMPAR_BUSCA = "limpar_busca"
MODO = "modo"
CATEGORIA = "categoria"
CONTEUDO = "conteudo"
LINGUAGEM = "linguagem"
LIMPAR_FILTROS = "limpar_filtros"
LIMPAR_TUDO = "limpar_tudo"
PAGINA = "pagina"
ABRIR = "abrir"
TROCAR_SENHA = "trocar_senha"
SAIR = "sair"
AJUDA = "ajuda"
SAUDACAO = "saudacao"      # chamaram o nome e não pediram nada

# Páginas, escritas exatamente como a navbar as rotula (`app.componentes`).
PAGINA_BUSCA = "Busca"
PAGINA_DASHBOARD = "Dashboard"
PAGINA_ADICIONAR = "Adicionar"
PAGINA_USUARIOS = "Usuários"

MODO_TEXTO = "Texto"
MODO_CODIGO = "Código"

PROXIMA = "proxima"
ANTERIOR = "anterior"

# O assistente atende pelo nome, e **só** pelo nome: nenhuma frase vira ação
# sem "Luiz" na frente. Isso é o que permite deixar o microfone aberto perto
# de uma conversa — o custo é ter que chamar sempre, inclusive apertando o
# botão. As variantes são o que o reconhecimento devolve na prática para o
# mesmo nome falado ("Luís", "Luiza", "Lui"); recusar por causa da grafia
# escolhida pelo navegador seria recusar por um detalhe que ninguém controla.
ATIVACOES = ("luiz", "luis", "luiza", "luisa", "lui", "ruiz")

# A resposta de quando chamam o nome e não pedem nada. Fica aqui, junto da
# gramática, porque é a outra ponta da mesma conversa.
SAUDACAO_RESPOSTA = (
    "Oi, em que posso lhe ajudar? Pode me perguntar tudo que quiser sobre o meu "
    "My Brain My Friend — se estiver contido nele, eu te ajudarei. Pode perguntar."
)


@dataclass(frozen=True)
class Comando:
    """O que o app deve fazer, mais a frase que confirma isso para o usuário.

    `valor` é sempre texto — inclusive para número de página e índice de
    resultado. Quem executa converte; assim o dataclass continua trivial de
    comparar nos testes.
    """
    acao: str
    valor: Optional[str] = None
    descricao: str = ""


# --------------------------------------------------------------- vocabulário

_ARTIGOS = (
    "o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das",
    "para", "pra", "pro", "no", "na", "nos", "nas", "em", "ao", "aos", "à", "às",
    "por", "meu", "minha", "esse", "essa", "este", "esta", "todo", "toda",
)

_VERBOS_NAVEGAR = (
    "ir para", "ir pra", "ir a", "ir ao", "ir", "vai para", "vai pra", "vai",
    "va para", "va pra", "va", "voltar para", "voltar pra", "voltar",
    "navegar para", "navegar", "abrir", "abre", "abra", "mostrar", "mostra",
    "me mostra", "me mostre", "mostre", "exibir", "exibe", "ver", "acessar",
    "acesse", "entrar em", "entra em", "pagina de", "pagina", "tela de",
    "tela", "aba de", "aba", "secao", "menu",
)

_VERBOS_BUSCAR = (
    "buscar", "busca", "busque", "buscar por", "busca por", "busque por",
    "pesquisar", "pesquisa", "pesquise", "pesquisar por", "pesquisa por",
    "pesquise por", "procurar", "procura", "procure", "procurar por",
    "procura por", "procure por", "encontrar", "encontre", "achar", "ache",
    "quero ver", "me mostre sobre", "sobre",
)

_VERBOS_ABRIR = (
    "abrir", "abre", "abra", "ver", "mostrar", "mostra", "me mostra",
    "me mostre", "mostre", "exibir", "exibe", "leia", "ler",
)

# Cada página aceita como for chamada em voz alta — inclusive por quem não
# leu o rótulo da navbar ("painel", "estatísticas", "contas").
_SINONIMOS_PAGINA: tuple[tuple[str, tuple[str, ...]], ...] = (
    (PAGINA_DASHBOARD, (
        "dashboard", "painel", "visao geral", "geral", "estatisticas",
        "estatistica", "graficos", "grafico", "numeros", "resumo", "metricas",
    )),
    (PAGINA_ADICIONAR, (
        "adicionar", "adicionar conteudo", "upload", "enviar", "enviar arquivo",
        "subir", "subir arquivo", "novo conteudo", "novo arquivo", "importar",
    )),
    (PAGINA_USUARIOS, (
        "usuarios", "usuario", "contas", "pessoas", "administracao",
        "gerenciar usuarios", "admin", "permissoes", "autorizacoes",
    )),
    (PAGINA_BUSCA, (
        "busca", "buscar", "pesquisa", "pesquisar", "procura", "inicio",
        "home", "principal", "comeco", "acervo",
    )),
)

_SINONIMOS_MODO: tuple[tuple[str, tuple[str, ...]], ...] = (
    (MODO_CODIGO, ("codigo", "code", "codigos", "programacao", "sintaxe")),
    (MODO_TEXTO, ("texto", "textos", "conceito", "conceitos", "explicacao")),
)

_ORDINAIS = {
    "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2,
    "terceiro": 3, "terceira": 3, "quarto": 4, "quarta": 4,
    "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
    "setimo": 7, "setima": 7, "oitavo": 8, "oitava": 8,
    "nono": 9, "nona": 9, "decimo": 10, "decima": 10, "ultimo": -1, "ultima": -1,
}

_NUMEROS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12,
}

_PONTUACAO = ".,;:!?…\"'“”‘’()[]{}«»·•"

# ------------------------------------------------- perguntas em voz natural
# Ninguém fala com o acervo em palavras-chave. Fala "explique como fazer uma
# procedure usando SQL Server" — e é aí que o full-text morre: a busca faz
# **AND** de todos os termos, então "explic & faz & procedure & sql & server"
# não casa com nada, mesmo o acervo tendo o material sobre procedure. A
# estrutura da pergunta precisa cair antes de virar termo de busca.

_ABERTURAS_DE_PERGUNTA = (
    "explique", "explica", "explicar", "explique-me", "me explique", "me explica",
    "ensine", "ensina", "ensinar", "me ensine", "me ensina", "como", "como e",
    "como que", "como faco", "como se", "o que e", "o que sao", "o que",
    "que e", "qual e", "qual", "quais", "quais sao", "para que serve",
    "pra que serve", "para que", "pra que", "quero saber", "quero entender",
    "quero aprender", "queria saber", "gostaria de saber", "preciso saber",
    "preciso entender", "me fale sobre", "fale sobre", "me diga", "diferenca entre",
    "exemplo de", "exemplos de", "um exemplo de", "me de um exemplo de",
)

# Palavras que só amarram a frase e nunca aparecem no material indexado. Sair
# fora é de propósito: com AND, sobrar termo demais devolve zero resultados,
# e errar para o lado de buscar demais é recuperável — errar para o lado de
# não achar nada parece que o acervo não tem o assunto.
_RUIDO_DE_PERGUNTA = frozenset((
    "explique", "explica", "explicar", "explicame", "explicacao",
    "ensine", "ensina", "ensinar", "mostre", "mostra", "mostrar",
    "diga", "dizer", "fale", "falar", "conte", "contar", "me", "mim", "eu",
    "quero", "queria", "gostaria", "preciso", "saber", "entender", "aprender",
    "ver", "veja", "vejo", "favor", "pode", "poderia", "ajuda", "ajudar",
    "como", "oque", "que", "qual", "quais", "quando", "onde", "porque", "pq",
    "fazer", "faz", "faco", "fazemos", "feito", "criar", "cria", "crio",
    "usar", "usando", "uso", "usa", "utilizar", "utilizando", "utiliza",
    "funciona", "funcionam", "serve", "servem", "e", "sao", "ser", "esta",
    "sobre", "jeito", "forma", "maneira", "exemplo", "exemplos",
    "tem", "ter", "isso", "isto", "aquilo", "algum", "alguma", "melhor",
    "com", "sem", "entre", "diferenca", "vez", "caso",
    # vícios de fala que o reconhecimento transcreve fielmente e que nunca são
    # assunto. "tipo" e "agora" ficam de fora: no acervo, "tipo de dado" e
    # "janela agora" são conteúdo de verdade.
    "entao", "ne", "ah", "eh", "hum", "olha", "pois", "mas", "ai", "opa",
    "oi", "ola", "bom", "dia", "boa", "tarde", "noite",
))


# ------------------------------------------------------------ normalização

def _sem_acento(palavra: str) -> str:
    decomposto = unicodedata.normalize("NFD", palavra)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def _tokenizar(frase: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(tokens normalizados, tokens originais) — sempre do mesmo tamanho.

    As duas listas andam juntas de propósito. O casamento das regras acontece
    no texto sem acento e em minúsculas ("codigo"), mas o termo de busca sai
    do original: quem pediu "regressão linear" quer isso na caixa de busca, e
    não "regressao linear" — o Postgres até acha os dois, a pessoa lê um só.
    """
    normalizados: list[str] = []
    originais: list[str] = []
    for bruto in frase.split():
        limpo = bruto.strip(_PONTUACAO)
        if not limpo:
            continue
        originais.append(limpo)
        normalizados.append(_sem_acento(limpo).lower())
    return tuple(normalizados), tuple(originais)


def normalizar(frase: str) -> str:
    """'  Modo  Código! ' -> 'modo codigo'."""
    return " ".join(_tokenizar(frase)[0])


def _casar_prefixo(tokens: Sequence[str], frases: Iterable[str]) -> Optional[int]:
    """Tamanho do maior prefixo de `tokens` que é uma das `frases`.

    O maior vence porque os gatilhos se contêm: "buscar por" precisa ganhar de
    "buscar", senão o "por" sobraria dentro do termo procurado.
    """
    melhor: Optional[int] = None
    for frase in frases:
        partes = frase.split()
        n = len(partes)
        if tuple(tokens[:n]) == tuple(partes) and (melhor is None or n > melhor):
            melhor = n
    return melhor


def _sem_enfeite(tokens: Sequence[str]) -> tuple[str, ...]:
    """Descarta artigos e preposições do início, quantos houver."""
    resto = list(tokens)
    while resto and resto[0] in _ARTIGOS:
        resto.pop(0)
    return tuple(resto)


def _numero(token: str) -> Optional[int]:
    """'3' ou 'três' -> 3. O reconhecimento devolve ora um, ora outro."""
    if token.isdigit():
        return int(token)
    return _NUMEROS.get(token)


# -------------------------------------------------------------- ativação

_CUMPRIMENTOS = ("ok", "ei", "oi", "ola", "hey", "opa", "e", "bom", "boa", "dia",
                 "tarde", "noite", "fala")
_CORTESIAS = ("por", "favor", "pode", "poderia", "me", "faz", "faca")


def _pular_chamado(normalizados: Sequence[str]) -> Optional[int]:
    """Quantos tokens do início são só o chamado, ou `None` se não chamaram.

    Uma função só para as duas perguntas ("chamaram?" e "onde começa o
    comando?") porque quando eram duas elas discordavam: "oi Luiz, próxima
    página" era reconhecida como chamado e mesmo assim entrava nas regras com
    o "oi Luiz" ainda na frente, virando busca pelo nome.
    """
    corte = 0
    while corte < len(normalizados) and (
        normalizados[corte] in _CUMPRIMENTOS or normalizados[corte] in _ARTIGOS
    ):
        corte += 1
    if corte >= len(normalizados) or normalizados[corte] not in ATIVACOES:
        return None
    corte += 1
    # "Luiz, por favor busca X" — a cortesia não faz parte do comando
    while corte < len(normalizados) and normalizados[corte] in _CORTESIAS:
        corte += 1
    return corte


def tem_ativacao(frase: str) -> bool:
    """True quando chamaram o assistente pelo nome.

    É o portão de tudo: sem o nome, nenhuma frase vira ação. É o que permite
    deixar o microfone aberto perto de uma conversa sem que a conversa
    execute comandos.
    """
    normalizados, _ = _tokenizar(frase)
    return _pular_chamado(normalizados) is not None


def _tirar_ativacao(
    normalizados: Sequence[str], originais: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    corte = _pular_chamado(normalizados)
    if corte is None:
        return tuple(normalizados), tuple(originais)
    return tuple(normalizados[corte:]), tuple(originais[corte:])


# -------------------------------------------------- da pergunta para o termo

def _filtrar_ruido(
    normalizados: Sequence[str], originais: Sequence[str],
) -> tuple[str, ...]:
    """Só o que tem chance de estar no acervo — nos originais, com acento.

    Devolve tupla vazia quando a frase inteira era estrutura ("me explica
    isso aí"): sem nenhum termo de conteúdo, buscar seria buscar por nada.
    """
    return tuple(
        original
        for norma, original in zip(normalizados, originais)
        if norma not in _RUIDO_DE_PERGUNTA and norma not in _ARTIGOS
    )


def termo_de_busca(frase: str) -> str:
    """A pergunta falada vira o termo que o Postgres tem chance de achar.

        "explique como fazer uma procedure usando SQL Server" -> "procedure SQL Server"
        "como fazer um group by usando pandas"                -> "group by pandas"

    Preserva acento e caixa do original: o índice acha os dois, mas quem lê a
    caixa de busca lê um só. Devolve "" quando não sobra conteúdo nenhum.
    """
    normalizados, originais = _tokenizar(frase or "")
    normalizados, originais = _tirar_ativacao(normalizados, originais)
    return " ".join(_filtrar_ruido(normalizados, originais))


def termos_essenciais(termo: str) -> str:
    """O mesmo termo sem as partículas curtas — a segunda tentativa da busca.

    "group by pandas" não acha nada quando o material indexou `df.groupby`
    como um token só: o "by" isolado nunca casa, e o AND do full-text derruba
    a frase inteira por causa dele. Descartar o que tem menos de três letras
    devolve "group pandas", que acha. Vale como *fallback*, nunca como
    primeira tentativa — em "left join on" as partículas são o assunto.
    """
    normalizados, originais = _tokenizar(termo or "")
    longos = tuple(o for n, o in zip(normalizados, originais) if len(n) >= 3)
    return " ".join(longos) if longos else ""


# ----------------------------------------------------------------- regras
# Cada regra recebe os tokens (normalizados + originais) e devolve um Comando
# ou None. `interpretar` chama todas na ordem em que estão listadas no fim.


def _regra_ajuda(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    frase = " ".join(norm)
    gatilhos = {
        "ajuda", "socorro", "comandos", "quais comandos", "o que posso falar",
        "o que voce faz", "o que eu posso dizer", "lista de comandos",
        "quais sao os comandos", "me ajuda", "mostrar comandos",
    }
    if frase in gatilhos:
        return Comando(AJUDA, descricao="Mostrando os comandos disponíveis")
    return None


def _regra_sair(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    """Sair exige frase inteira — ver a nota de segurança no topo do módulo."""
    frase = " ".join(norm)
    gatilhos = {
        "encerrar sessao", "encerrar a sessao", "sair do sistema",
        "sair da conta", "fazer logout", "quero sair do sistema",
        "desconectar do sistema", "encerrar minha sessao",
    }
    if frase in gatilhos:
        return Comando(SAIR, descricao="Encerrando a sessão")
    return None


def _regra_trocar_senha(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    """O verbo tem que vir *antes* de "senha" — senão "buscar senha forte",
    que é uma busca legítima no acervo, abriria a tela de troca."""
    if "senha" not in norm:
        return None
    onde = norm.index("senha")
    verbos = ("trocar", "mudar", "alterar", "atualizar", "redefinir")
    if any(verbo in norm[:onde] for verbo in verbos):
        return Comando(TROCAR_SENHA, descricao="Abrindo a troca de senha")
    if " ".join(norm) in ("nova senha", "minha senha", "senha nova"):
        return Comando(TROCAR_SENHA, descricao="Abrindo a troca de senha")
    return None


def _regra_limpar(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    frase = " ".join(norm)
    if frase in ("limpar tudo", "limpar", "recomecar", "comecar de novo", "resetar",
                 "apagar tudo", "do zero", "nova busca", "limpar a tela"):
        return Comando(LIMPAR_TUDO, descricao="Limpando busca e filtros")
    if any(frase == f"{verbo} {alvo}" or frase == f"{verbo} a {alvo}" or frase == f"{verbo} o {alvo}"
           for verbo in ("limpar", "apagar", "remover", "tirar", "zerar")
           for alvo in ("busca", "pesquisa", "termo", "texto")):
        return Comando(LIMPAR_BUSCA, descricao="Limpando o termo de busca")
    if any(frase == f"{verbo} {alvo}" or frase == f"{verbo} os {alvo}"
           for verbo in ("limpar", "apagar", "remover", "tirar", "zerar")
           for alvo in ("filtros", "filtro")):
        return Comando(LIMPAR_FILTROS, descricao="Removendo os filtros")
    if frase in ("todas as categorias", "todas categorias", "sem filtro", "sem filtros",
                 "todo o conteudo", "todas as linguagens"):
        return Comando(LIMPAR_FILTROS, descricao="Removendo os filtros")
    return None


def _regra_modo(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    resto = _sem_enfeite(norm)
    gatilho = _casar_prefixo(resto, (
        "modo", "modo de", "mudar para modo", "trocar para modo", "buscar em",
        "busca em", "buscar por", "busca por", "procurar em", "alternar para",
    ))
    if gatilho is None:
        return None
    alvo = _sem_enfeite(resto[gatilho:])
    if len(alvo) != 1:
        return None
    for modo, sinonimos in _SINONIMOS_MODO:
        if alvo[0] in sinonimos:
            return Comando(MODO, modo, f"Modo de busca: {modo}")
    return None


def _regra_pagina(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    frase = " ".join(_sem_enfeite(norm))
    if frase in ("proxima pagina", "proxima", "pagina seguinte", "seguinte",
                 "avancar", "avanca", "avance", "mais resultados", "continuar",
                 "proximos resultados", "pagina proxima"):
        return Comando(PAGINA, PROXIMA, "Próxima página")
    if frase in ("pagina anterior", "anterior", "voltar pagina", "volta pagina",
                 "pagina de tras", "resultados anteriores", "retroceder",
                 "pagina anterior por favor"):
        return Comando(PAGINA, ANTERIOR, "Página anterior")
    if frase in ("primeira pagina", "voltar ao inicio", "inicio da lista",
                 "voltar para o inicio", "comeco da lista"):
        return Comando(PAGINA, "1", "Voltando para a primeira página")

    tokens = _sem_enfeite(norm)
    gatilho = _casar_prefixo(tokens, ("pagina", "ir para pagina", "ir pagina", "va para pagina"))
    if gatilho is None:
        return None
    alvo = _sem_enfeite(tokens[gatilho:])
    if len(alvo) != 1:
        return None
    numero = _numero(alvo[0])
    if numero is None or numero < 1:
        return None
    return Comando(PAGINA, str(numero), f"Indo para a página {numero}")


def _regra_abrir(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    """"abrir o terceiro resultado" — abre o card N da página atual.

    Exige verbo *ou* a palavra "resultado": um número solto ("três") pode ser
    ruído da sala, e abrir um arquivo é barulhento o bastante para atrapalhar
    quem está lendo a tela.
    """
    tokens = _sem_enfeite(norm)
    gatilho = _casar_prefixo(tokens, _VERBOS_ABRIR)
    tinha_verbo = gatilho is not None
    resto = _sem_enfeite(tokens[gatilho:] if gatilho else tokens)

    citou_resultado = False
    if resto and resto[0] in ("resultado", "resultados", "item", "card", "bloco"):
        citou_resultado = True
        resto = _sem_enfeite(resto[1:])

    if not resto:
        return None
    posicao = _ORDINAIS.get(resto[0])
    if posicao is None:
        posicao = _numero(resto[0])
    if posicao is None or posicao == 0:
        return None

    cauda = resto[1:]
    while cauda and (cauda[0] in _ARTIGOS or cauda[0] in (
            "resultado", "resultados", "item", "card", "bloco", "arquivo",
            "conteudo", "lista", "busca", "pagina")):
        if cauda[0] in ("resultado", "resultados", "item", "card", "bloco"):
            citou_resultado = True
        cauda = cauda[1:]
    if cauda:
        return None
    if not tinha_verbo and not citou_resultado:
        return None

    if posicao == -1:
        return Comando(ABRIR, "-1", "Abrindo o último resultado")
    return Comando(ABRIR, str(posicao), f"Abrindo o resultado {posicao}")


def _regra_filtro(norm: Sequence[str], orig: Sequence[str]) -> Optional[Comando]:
    """"categoria Databricks", "linguagem python", "conteúdo aula 3".

    O valor sai cru daqui: quais categorias existem é pergunta para o banco,
    não para a gramática. Quem executa resolve com `escolher_opcao`.
    """
    alvos = (
        (CATEGORIA, ("categoria", "categorias", "filtrar categoria",
                     "filtrar por categoria", "so da categoria", "na categoria",
                     "da categoria", "materia", "disciplina")),
        (LINGUAGEM, ("linguagem", "linguagens", "filtrar linguagem",
                     "filtrar por linguagem", "na linguagem", "escrito em",
                     "so em")),
        (CONTEUDO, ("conteudo", "conteudos", "arquivo", "filtrar conteudo",
                    "filtrar por conteudo", "no arquivo", "no conteudo",
                    "aula", "material")),
    )
    tokens = _sem_enfeite(norm)
    # os originais precisam andar junto para o valor sair com acento e caixa
    corte_inicial = len(norm) - len(tokens)

    for acao, gatilhos in alvos:
        gatilho = _casar_prefixo(tokens, gatilhos)
        if gatilho is None:
            continue
        # "aula 3" é o nome do conteúdo, não um gatilho a descartar
        consumidos = gatilho if tokens[:gatilho] != ("aula",) else 0
        inicio = corte_inicial + consumidos
        valor_norm = _sem_enfeite(norm[inicio:])
        if not valor_norm:
            return None
        valor = " ".join(orig[len(norm) - len(valor_norm):])
        rotulo = {CATEGORIA: "Categoria", LINGUAGEM: "Linguagem", CONTEUDO: "Conteúdo"}[acao]
        return Comando(acao, valor, f"{rotulo}: {valor}")
    return None


def _regra_pergunta(norm: Sequence[str], orig: Sequence[str]) -> Optional[Comando]:
    """"explique como fazer uma procedure em SQL Server" -> busca por "procedure SQL Server".

    Vem antes da navegação de propósito: "o que é um dashboard" é uma pergunta
    sobre o assunto, não um pedido para abrir a página Dashboard. A navegação
    continua ganhando quando a frase é só o nome da página ("dashboard").
    """
    # nos tokens crus *e* sem os artigos: "para que serve" começa por uma
    # palavra que `_sem_enfeite` descarta, e "o que é" começa por outra que ele
    # precisa descartar — nenhuma das duas casa nas duas formas
    if all(
        _casar_prefixo(tokens, _ABERTURAS_DE_PERGUNTA) is None
        for tokens in (norm, _sem_enfeite(norm))
    ):
        return None
    termo = " ".join(_filtrar_ruido(norm, orig))
    if not termo:
        return None
    return Comando(BUSCAR, termo, f"Buscando “{termo}”")


def _regra_navegar(norm: Sequence[str], _orig: Sequence[str]) -> Optional[Comando]:
    tokens = _sem_enfeite(norm)
    gatilho = _casar_prefixo(tokens, _VERBOS_NAVEGAR)
    if gatilho is not None:
        tokens = _sem_enfeite(tokens[gatilho:])
    if not tokens:
        return None
    frase = " ".join(tokens)
    for pagina, sinonimos in _SINONIMOS_PAGINA:
        if frase in sinonimos:
            return Comando(NAVEGAR, pagina, f"Abrindo {pagina}")
    return None


def _regra_buscar(norm: Sequence[str], orig: Sequence[str]) -> Optional[Comando]:
    tokens = _sem_enfeite(norm)
    corte_inicial = len(norm) - len(tokens)
    gatilho = _casar_prefixo(tokens, _VERBOS_BUSCAR)
    if gatilho is None:
        return None

    termo_norm = _sem_enfeite(tokens[gatilho:])
    if not termo_norm:
        return None
    # "buscar sobre regressão" / "procurar pelo termo X" — ruído entre o verbo
    # e o que interessa
    while termo_norm and termo_norm[0] in ("sobre", "termo", "assunto", "algo", "tudo"):
        termo_norm = _sem_enfeite(termo_norm[1:])
    if not termo_norm:
        return None

    inicio = len(norm) - len(termo_norm)
    if inicio < corte_inicial:
        return None
    termo = " ".join(orig[inicio:])
    return Comando(BUSCAR, termo, f"Buscando “{termo}”")


# A ordem é a regra de desempate — ver a nota no topo do módulo.
_REGRAS = (
    _regra_ajuda,
    _regra_sair,
    _regra_trocar_senha,
    _regra_limpar,
    _regra_pagina,
    _regra_modo,
    _regra_abrir,
    _regra_filtro,
    _regra_pergunta,
    _regra_navegar,
    _regra_buscar,
)


def interpretar(frase: str) -> Optional[Comando]:
    """A frase falada vira um `Comando`, ou `None` se não for reconhecida.

    O nome é descartado antes das regras — "Luiz, próxima página" e "próxima
    página" chegam iguais aqui. Quem exige o nome é `app.voz`, com
    `tem_ativacao`; esta camada só precisa saber que ele não faz parte do
    comando. A exceção é o nome sozinho, que já é a mensagem inteira.
    """
    normalizados, originais = _tokenizar(frase or "")
    chamaram = _pular_chamado(normalizados) is not None
    normalizados, originais = _tirar_ativacao(normalizados, originais)
    if not normalizados:
        return Comando(SAUDACAO, descricao=SAUDACAO_RESPOSTA) if chamaram else None

    for regra in _REGRAS:
        comando = regra(normalizados, originais)
        if comando is not None:
            return comando
    return None


def interpretar_livre(frase: str) -> Optional[Comando]:
    """`interpretar`, e o que sobrar vira busca no acervo.

    A diferença é o que acontece com a frase desconhecida. `interpretar`
    devolve `None` — certo para quem pilota a interface, porque executar a
    ação errada é pior que não executar. Aqui a sobra vira um `BUSCAR`: no
    acervo, "frase que não é comando" quase sempre é assunto, e o pior caso
    de buscar demais é uma lista vazia, que se desfaz sozinha na próxima
    frase. Quem chama valida o termo contra o banco antes de trocar a tela.

    Devolve `None` só quando não sobra termo nenhum ("é, então…").
    """
    comando = interpretar(frase)
    if comando is not None:
        return comando
    termo = termo_de_busca(frase)
    if not termo:
        return None
    return Comando(BUSCAR, termo, f"Buscando “{termo}”")


# -------------------------------------------------- casar com o que existe

def escolher_opcao(falado: str, opcoes: Sequence[str]) -> Optional[str]:
    """A opção real mais parecida com o que foi dito, ou `None`.

    O reconhecimento devolve "data brics" para "Databricks" e "pyton" para
    "python"; exigir igualdade exata jogaria fora quase todo filtro por voz.
    A escada vai do mais seguro ao mais tolerante e para no primeiro acerto —
    e o último degrau tem corte alto, porque um filtro errado esconde
    resultados sem avisar que escondeu.
    """
    pares = [(normalizar(opcao), opcao) for opcao in opcoes if normalizar(opcao)]
    alvo = normalizar(falado)
    if not alvo or not pares:
        return None

    for norma, opcao in pares:
        if norma == alvo:
            return opcao
    for norma, opcao in pares:
        if norma.startswith(alvo) or alvo.startswith(norma):
            return opcao

    palavras = set(alvo.split())
    for norma, opcao in pares:
        if palavras <= set(norma.split()):
            return opcao
    for norma, opcao in pares:
        if alvo in norma:
            return opcao

    # Último degrau: semelhança de letras, para o caso "databriks" → "Databricks".
    # A comparação é feita também palavra a palavra porque o rótulo real carrega
    # a subcategoria ("Databricks · Módulo 1") — contra a string inteira, o
    # acerto parcial afundaria abaixo de qualquer corte razoável.
    melhor_opcao: Optional[str] = None
    melhor_nota = 0.0
    for norma, opcao in pares:
        candidatos = [norma, *norma.split()]
        nota = max(
            difflib.SequenceMatcher(None, alvo, candidato).ratio()
            for candidato in candidatos
        )
        if nota > melhor_nota:
            melhor_nota, melhor_opcao = nota, opcao
    return melhor_opcao if melhor_nota >= 0.8 else None


# ------------------------------------------------------------------- ajuda
# Uma fonte só: a tela de ajuda mostra estes exemplos e os testes garantem
# que cada um deles ainda é interpretado. Exemplo que quebra vira teste
# vermelho, não instrução mentirosa na tela.

EXEMPLOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Chamar", (
        "Luiz",
        "oi Luiz",
    )),
    ("Perguntar", (
        "Luiz, como fazer um group by usando pandas",
        "Luiz, explique como criar uma procedure em SQL Server",
        "Luiz, o que é uma janela de tempo",
    )),
    ("Navegar", (
        "Luiz, ir para o dashboard",
        "Luiz, abrir adicionar",
        "Luiz, voltar para a busca",
    )),
    ("Buscar", (
        "Luiz, buscar regressão linear",
        "Luiz, procurar por LEFT JOIN",
        "Luiz, limpar a busca",
    )),
    ("Modo de busca", (
        "Luiz, modo código",
        "Luiz, modo texto",
    )),
    ("Filtrar", (
        "Luiz, categoria Databricks",
        "Luiz, linguagem python",
        "Luiz, limpar filtros",
    )),
    ("Resultados", (
        "Luiz, próxima página",
        "Luiz, página anterior",
        "Luiz, abrir o segundo resultado",
    )),
    ("Conta", (
        "Luiz, trocar minha senha",
        "Luiz, encerrar sessão",
    )),
)
