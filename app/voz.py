"""Assistente de voz — ouve no navegador, executa no `session_state`.

## Por que não "clicar no botão"

A ideia original era simular o clique. Não dá, e não precisa: em Streamlit o
botão não é um objeto que existe entre um rerun e outro — ele é redesenhado
do zero a cada execução do script, e o que ele faz de verdade é escrever no
`st.session_state`. Então o assistente pula a intermediação e **escreve o
estado direto, antes dos widgets nascerem**. O efeito na tela é idêntico ao
do clique, e não depende de achar um elemento no DOM que pode ter mudado de
lugar na próxima versão do Streamlit.

Isso amarra uma regra de ordem que o `streamlit_app` precisa respeitar:
`processar_pendente()` roda **antes** da navbar e das páginas. Depois que um
widget é instanciado, escrever na chave dele já não muda a tela desta rodada.

## O caminho de uma frase

    microfone (navegador)
      → controlador JS injetado na página                  [_PONTE_JS]
      → campo de texto do Streamlit                        [painel]
      → callback `_receber` guarda em `voz_pendente`
      → rerun → chamou "Luiz"? senão para aqui             [processar_pendente]
      → `interpretar_livre`: comando, ou busca pelo assunto
      → executa escrevendo no `session_state`              [_executar]

## Duas coisas que a barra promete e o resto do módulo cumpre

**Só responde pelo nome.** Nenhuma frase vira ação sem "Luiz" na frente,
falada ou digitada. É o que permite deixar o microfone aberto numa sala com
gente conversando sem que a conversa navegue pelo app.

**Pergunta desconhecida vira busca, mas só depois de o banco confirmar.**
O acervo é grande e o vocabulário de comandos é pequeno; recusar tudo que
não é comando desperdiçaria o conteúdo. Então a sobra vira termo de busca —
e `_fazer_buscar` conta os resultados *antes* de trocar a tela, porque trocar
para mostrar "nenhum resultado" custa a busca que a pessoa já tinha.

O campo de texto no meio não é gambiarra: é a única via oficial de um script
do navegador devolver texto para o Python sem construir um componente React
com build próprio. E ele é também a interface de fallback — dá para digitar
os mesmos comandos, o que torna o assistente testável e utilizável em
navegador sem reconhecimento de fala.

## O controlador roda na página, não no iframe

`st.iframe` cria um iframe novo a cada rerun; um reconhecimento de fala que
morasse lá dentro morreria a cada comando executado. Então o iframe é só um
instalador: ele injeta o controlador como um `<script>` na página principal,
onde `window` sobrevive aos reruns.

O que é injetado é o **código**, não só o botão — e essa distinção é o motivo
de o microfone funcionar no `localhost` e não no Streamlit Cloud. Um script
que roda dentro do iframe cria um `SpeechRecognition` preso ao documento do
iframe, e esse documento nunca recebe *user activation*: o clique aconteceu
no botão da página, e ativação sobe para os ancestrais, nunca desce para os
filhos. Sem ativação, o Chrome não abre o pedido de permissão do microfone.
No `localhost` isso passa despercebido porque a permissão já foi concedida
uma vez e não há mais o que perguntar; num domínio novo, onde a pergunta é
obrigatória, o mesmo clique simplesmente não produz nada. Rodando na página,
o reconhecimento herda a ativação do clique e o navegador pergunta.
"""
import html
import json
from typing import Optional

import streamlit as st

from acervo.core.exceptions import BuscaError
from acervo.search import busca_service
from acervo.voz import comandos as cmd
from app import componentes as comp

# ------------------------------------------------------------------ estado
# Chaves do assistente.
COMANDO = "voz_comando"          # campo de texto — a ponte do navegador escreve aqui
PENDENTE = "voz_pendente"        # frase aguardando execução no próximo run
ULTIMO = "voz_ultimo"            # (nível, mensagem) da última confirmação
ABRIR_INDICE = "voz_abrir_indice"    # a busca consome e abre o card N
TOTAL_PAGINAS = "voz_total_paginas"  # a busca publica; a paginação por voz respeita
ESCUTA_CONTINUA = "voz_continua"

# Chaves de widgets de *outras* telas, que o assistente pilota. Ficam listadas
# juntas de propósito: se uma página renomear a sua, o assistente para de
# funcionar em silêncio, e esta lista é o primeiro lugar onde procurar.
_NAV = "nav_paginas"             # app/streamlit_app.py
_TERMO = "termo_busca"           # app/paginas/busca.py
_MODO = "modo_busca"
_CATEGORIA = "filtro_categoria"
_CONTEUDO = "filtro_conteudo"
_LINGUAGEM = "filtro_linguagem"
_PAGINA = "pagina_busca"
_CONTA = "mostrar_conta"         # app/streamlit_app.py


# ------------------------------------------------------------- dados do banco

@st.cache_data(ttl=600, show_spinner=False)
def _opcoes_de_filtro() -> dict:
    return busca_service.opcoes_de_filtro()


@st.cache_data(ttl=600, show_spinner=False)
def _conteudos(categoria_id: Optional[int]):
    return busca_service.conteudos_da_categoria(categoria_id)


def _rotulos_de_categoria() -> dict[str, int]:
    """Rótulo exibido no dropdown → id. Igual ao que a busca monta."""
    opcoes = _opcoes_de_filtro()
    return {
        comp.rotulo_categoria(c.nome, c.subcategoria): c.id
        for c in opcoes["categorias"]
    }


# -------------------------------------------------------------- execução
# Cada `_fazer_*` devolve (nível, mensagem) — o nível é o mesmo vocabulário do
# Streamlit ("ok", "aviso", "erro") e vira cor do badge de confirmação.


def _ir_para(pagina: str) -> None:
    st.session_state[_NAV] = pagina
    st.session_state[_CONTA] = False


def _fazer_navegar(comando: cmd.Comando, eh_admin: bool) -> tuple[str, str]:
    if comando.valor == cmd.PAGINA_USUARIOS and not eh_admin:
        return "aviso", "A página de usuários é só para administradores."
    _ir_para(comando.valor)
    return "ok", comando.descricao


_MODOS_SERVICO = {cmd.MODO_TEXTO: "texto", cmd.MODO_CODIGO: "codigo"}


@st.cache_data(ttl=300, show_spinner=False)
def _contar(termo, modo, categoria_id, linguagem, arquivo_caminho) -> int:
    """Quantos blocos esse termo acha — `LIMIT 1`, só o total da janela."""
    try:
        return busca_service.buscar(
            termo, modo=modo, categoria_id=categoria_id, linguagem=linguagem,
            arquivo_caminho=arquivo_caminho, pagina=1, limite=1,
        ).total
    except BuscaError:
        return 0


def _filtros_ativos() -> tuple[Optional[int], Optional[str], Optional[str]]:
    """(categoria_id, linguagem, arquivo) como a página de busca os aplicaria."""
    rotulos = _rotulos_de_categoria()
    categoria_id = rotulos.get(st.session_state.get(_CATEGORIA, comp.FILTRO_TODAS))
    linguagem = st.session_state.get(_LINGUAGEM, comp.FILTRO_TODAS)
    conteudo = st.session_state.get(_CONTEUDO, comp.FILTRO_TODO_CONTEUDO)
    caminho = comp.rotulos_de_conteudo(_conteudos(categoria_id)).get(conteudo)
    return (
        categoria_id,
        None if linguagem == comp.FILTRO_TODAS else linguagem,
        caminho,
    )


def _fazer_buscar(comando: cmd.Comando) -> tuple[str, str]:
    """Só troca a tela depois de o banco confirmar que há o que mostrar.

    Perguntar por voz é barato e errar a transcrição é comum; jogar fora a
    busca que estava na tela para mostrar "nenhum resultado" pune quem
    perguntou. Então a ordem é: conta primeiro, navega depois.

    A escada tem dois degraus, e os dois existem por um motivo observado:
    o termo essencial (sem as partículas curtas) resgata "group by pandas",
    que o AND do full-text derruba por causa do "by"; e a busca sem filtros
    resgata a pergunta feita com um filtro antigo ainda ligado na tela — aí
    a pergunta ganha do filtro, porque foi ela que a pessoa acabou de fazer.
    """
    modo = _MODOS_SERVICO.get(st.session_state.get(_MODO, cmd.MODO_TEXTO), "texto")
    termos = [comando.valor]
    essenciais = cmd.termos_essenciais(comando.valor)
    if essenciais and essenciais != comando.valor:
        termos.append(essenciais)

    try:
        filtros = _filtros_ativos()
    except BuscaError:
        filtros = (None, None, None)

    for termo in termos:
        total = _contar(termo, modo, *filtros)
        if total:
            return _mostrar_busca(termo, total, "")

    if any(filtros):
        for termo in termos:
            total = _contar(termo, modo, None, None, None)
            if total:
                _zerar_filtros()
                return _mostrar_busca(termo, total, " (removi os filtros)")

    return "aviso", f"Não achei nada sobre “{comando.valor}” no acervo."


def _mostrar_busca(termo: str, total: int, nota: str) -> tuple[str, str]:
    _ir_para(cmd.PAGINA_BUSCA)
    st.session_state[_TERMO] = termo
    st.session_state[_PAGINA] = 1
    plural = "resultado" if total == 1 else "resultados"
    return "ok", f"{total} {plural} para “{termo}”{nota}"


def _fazer_filtro(comando: cmd.Comando) -> tuple[str, str]:
    """Casa o que foi dito com uma opção que existe de verdade.

    Escrever no `session_state` um valor fora da lista do selectbox derruba a
    página inteira com `StreamlitAPIException` — por isso nada aqui é escrito
    antes de `escolher_opcao` confirmar que a opção existe.
    """
    _ir_para(cmd.PAGINA_BUSCA)
    try:
        if comando.acao == cmd.CATEGORIA:
            rotulos = _rotulos_de_categoria()
            escolha = cmd.escolher_opcao(comando.valor, list(rotulos))
            if escolha is None:
                return "aviso", f"Não achei a categoria “{comando.valor}”."
            st.session_state[_CATEGORIA] = escolha
            st.session_state[_CONTEUDO] = comp.FILTRO_TODO_CONTEUDO
            return "ok", f"Categoria: {escolha}"

        if comando.acao == cmd.LINGUAGEM:
            linguagens = list(_opcoes_de_filtro()["linguagens"])
            escolha = cmd.escolher_opcao(comando.valor, linguagens)
            if escolha is None:
                return "aviso", f"Não achei a linguagem “{comando.valor}”."
            st.session_state[_LINGUAGEM] = escolha
            return "ok", f"Linguagem: {escolha}"

        # conteúdo: as opções dependem da categoria escolhida agora
        rotulos = _rotulos_de_categoria()
        atual = st.session_state.get(_CATEGORIA, comp.FILTRO_TODAS)
        conteudos = comp.rotulos_de_conteudo(_conteudos(rotulos.get(atual)))
        escolha = cmd.escolher_opcao(comando.valor, list(conteudos))
        if escolha is None:
            return "aviso", f"Não achei o conteúdo “{comando.valor}”."
        st.session_state[_CONTEUDO] = escolha
        return "ok", f"Conteúdo: {comp.resumir(escolha, 60)}"
    except BuscaError as e:
        return "erro", f"Não consegui ler os filtros: {e}"


def _zerar_filtros() -> None:
    st.session_state[_CATEGORIA] = comp.FILTRO_TODAS
    st.session_state[_CONTEUDO] = comp.FILTRO_TODO_CONTEUDO
    st.session_state[_LINGUAGEM] = comp.FILTRO_TODAS


def _fazer_limpar(acao: str) -> tuple[str, str]:
    if acao in (cmd.LIMPAR_BUSCA, cmd.LIMPAR_TUDO):
        st.session_state[_TERMO] = ""
        st.session_state[_PAGINA] = 1
    if acao in (cmd.LIMPAR_FILTROS, cmd.LIMPAR_TUDO):
        _zerar_filtros()
    _ir_para(cmd.PAGINA_BUSCA)
    return "ok", {
        cmd.LIMPAR_BUSCA: "Busca limpa",
        cmd.LIMPAR_FILTROS: "Filtros removidos",
        cmd.LIMPAR_TUDO: "Busca e filtros limpos",
    }[acao]


def nova_pagina(valor: str, atual: int, total: int) -> Optional[int]:
    """Para onde a paginação vai — ou `None` quando já está na ponta.

    Pura de propósito: é a única aritmética do módulo e a que mais erra na
    borda (pedir "próxima" na última página não pode buscar uma página vazia).
    """
    if total < 1:
        return None
    if valor == cmd.PROXIMA:
        destino = atual + 1
    elif valor == cmd.ANTERIOR:
        destino = atual - 1
    else:
        try:
            destino = int(valor)
        except ValueError:
            return None
    if destino < 1 or destino > total:
        return None
    return destino


def _fazer_pagina(comando: cmd.Comando) -> tuple[str, str]:
    total = int(st.session_state.get(TOTAL_PAGINAS, 0))
    atual = int(st.session_state.get(_PAGINA, 1))
    if total < 1:
        return "aviso", "Não há resultados para paginar."
    destino = nova_pagina(comando.valor, atual, total)
    if destino is None:
        limite = "última" if comando.valor == cmd.PROXIMA else "primeira"
        return "aviso", f"Você já está na {limite} página."
    st.session_state[_PAGINA] = destino
    return "ok", f"Página {destino} de {total}"


def _fazer_abrir(comando: cmd.Comando) -> tuple[str, str]:
    st.session_state[ABRIR_INDICE] = int(comando.valor)
    _ir_para(cmd.PAGINA_BUSCA)
    return "ok", comando.descricao


def _executar(comando: cmd.Comando, *, eh_admin: bool) -> tuple[str, str]:
    acao = comando.acao
    if acao == cmd.NAVEGAR:
        return _fazer_navegar(comando, eh_admin)
    if acao == cmd.BUSCAR:
        return _fazer_buscar(comando)
    if acao in (cmd.CATEGORIA, cmd.LINGUAGEM, cmd.CONTEUDO):
        return _fazer_filtro(comando)
    if acao in (cmd.LIMPAR_BUSCA, cmd.LIMPAR_FILTROS, cmd.LIMPAR_TUDO):
        return _fazer_limpar(acao)
    if acao == cmd.MODO:
        st.session_state[_MODO] = comando.valor
        st.session_state[_PAGINA] = 1
        _ir_para(cmd.PAGINA_BUSCA)
        return "ok", comando.descricao
    if acao == cmd.PAGINA:
        return _fazer_pagina(comando)
    if acao == cmd.ABRIR:
        return _fazer_abrir(comando)
    if acao == cmd.TROCAR_SENHA:
        st.session_state[_CONTA] = True
        return "ok", comando.descricao
    if acao == cmd.SAUDACAO:
        return "saudacao", comando.descricao
    if acao == cmd.AJUDA:
        return "ajuda", comando.descricao
    if acao == cmd.SAIR:
        return "sair", comando.descricao
    return "aviso", "Comando reconhecido, mas sem ação associada."


# ------------------------------------------------------------ ciclo do painel

def _receber() -> None:
    """Callback do campo de texto: guarda a frase e esvazia o campo.

    Esvaziar é o que permite repetir o mesmo comando. O Streamlit só avisa o
    servidor quando o valor *muda*; sem a limpeza, dizer "próxima página" duas
    vezes seguidas escreveria o mesmo texto e a segunda vez seria ignorada.
    Mexer na própria chave do widget é legítimo aqui — dentro do callback, e
    não durante o desenho da página.
    """
    frase = (st.session_state.get(COMANDO) or "").strip()
    st.session_state[COMANDO] = ""
    if frase:
        st.session_state[PENDENTE] = frase


def processar_pendente(*, eh_admin: bool) -> None:
    """Executa a frase que chegou. Chamar no topo do run, antes dos widgets.

    O portão do nome é aqui, e vale para tudo — falado ou digitado. Uniforme
    de propósito: "o assistente só responde quando chamam por ele" é uma
    regra que a pessoa aprende uma vez, e uma exceção para o teclado só
    serviria para tornar o comportamento difícil de prever.
    """
    frase = st.session_state.pop(PENDENTE, None)
    if not frase:
        return

    if not cmd.tem_ativacao(frase):
        st.session_state[ULTIMO] = (
            "aviso", f"Chame pelo nome primeiro — “Luiz, {frase}”."
        )
        return

    comando = cmd.interpretar_livre(frase)
    if comando is None:
        st.session_state[ULTIMO] = ("saudacao", cmd.SAUDACAO_RESPOSTA)
        return

    nivel, mensagem = _executar(comando, eh_admin=eh_admin)
    st.session_state[ULTIMO] = (nivel, mensagem)

    if nivel == "sair":
        from app import sessao  # import local: `sessao` não é usado em mais nada aqui
        sessao.encerrar_sessao()
        st.rerun()


# ------------------------------------------------------------------- ponte JS
# `_CONTROLADOR_JS` roda na página principal; `_PONTE_JS` roda no iframe e só
# serve para instalá-lo. Ver "O controlador roda na página" no topo do módulo.

_CONTROLADOR_JS = """
(function () {
  const W = window, D = W.document;
  const ATIVACOES = __ATIVACOES__;

  // O app dentro de outro site (o painel do Streamlit Cloud embute a aplicação
  // num iframe) só tem microfone se o container liberar, e não há como pedir
  // isso daqui. Vale como diagnóstico: transforma um "não funciona" mudo em
  // uma instrução — abrir o app na própria aba.
  const embutido = W.self !== W.top;

  const Fala = W.SpeechRecognition || W.webkitSpeechRecognition;
  const ctrl = {
    querendo: false,   // o que a pessoa pediu (botão ligado)
    rodando: false,    // o que o reconhecimento está fazendo de verdade
    partindo: false,   // start() chamado, onstart ainda não veio
    recado: '',
    continuo: false,   // chega pela ponte, em `modo()`
    rec: null,
    botao: null,
    status: null,
  };

  function campo() {
    return D.querySelector('[class*="st-key-voz_comando"] input');
  }

  // Entregar texto ao Streamlit é mais chato do que parece, e cada linha
  // abaixo é resultado de tentativa e erro no navegador:
  //
  // * Escrever `.value` direto não avisa o React — ele rastreia o valor por
  //   fora do DOM. Só o setter nativo do prototype fura esse rastreio, e é
  //   ele que faz o campo aparecer preenchido.
  // * Preencher não é confirmar. A confirmação só acontece com um Enter, e
  //   um Enter só de `keydown` é ignorado: o trio keydown/keypress/keyup
  //   precisa vir inteiro e `cancelable`, senão o React não o trata como
  //   tecla de verdade.
  // * `blur()` sozinho não resolve: sem foco anterior ele não emite evento.
  //
  // Se um dia isto parar de funcionar (o Streamlit não promete esta via), o
  // sintoma é claro — o texto aparece no campo e nada acontece — e o campo
  // continua funcionando na digitação normal.
  function enviar(texto, tentativa) {
    const alvo = campo();
    if (!alvo) {
      // rerun em andamento: o campo volta em instantes, e perder a frase aqui
      // seria perder justamente a que a pessoa acabou de falar
      if ((tentativa || 0) < 20) W.setTimeout(() => enviar(texto, (tentativa || 0) + 1), 100);
      return;
    }
    const setter = Object.getOwnPropertyDescriptor(
      W.HTMLInputElement.prototype, 'value').set;
    alvo.focus();
    setter.call(alvo, texto);
    alvo.dispatchEvent(new W.Event('input', { bubbles: true }));
    for (const tipo of ['keydown', 'keypress', 'keyup']) {
      alvo.dispatchEvent(new W.KeyboardEvent(tipo, {
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, charCode: 13,
        bubbles: true, cancelable: true,
      }));
    }
    alvo.dispatchEvent(new W.Event('change', { bubbles: true }));
  }

  // Portão de ruído, não a gramática: em escuta contínua o microfone ouve a
  // sala inteira, e mandar tudo para o servidor faria um rerun por frase dita
  // por perto. Quem decide o que a frase significa continua sendo o Python.
  function chamaram(texto) {
    const limpo = texto.toLowerCase()
      .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').trim();
    return ATIVACOES.some(nome => limpo.split(/[^a-z0-9]+/).slice(0, 3).includes(nome));
  }

  function pintar() {
    if (!ctrl.botao) return;
    const ouvindo = ctrl.querendo;
    ctrl.botao.classList.toggle('ouvindo', ouvindo);
    ctrl.botao.textContent = ouvindo ? '● Ouvindo' : '🎙 Falar';
    ctrl.botao.title = ouvindo ? 'Parar de ouvir' : 'Começar a ouvir';
    if (ctrl.status && !ctrl.recado) {
      ctrl.status.textContent = !Fala
        ? 'Este navegador não reconhece fala — use o campo ao lado.'
        : ouvindo ? 'Comece por “Luiz…”' : '';
    }
  }

  // Um recado é o que a pessoa precisa fazer ("permissão negada"); fica na
  // tela até a próxima ação, senão some antes de ser lido.
  function recadar(texto) {
    ctrl.recado = texto;
    if (ctrl.status) ctrl.status.textContent = texto;
    W.setTimeout(() => { if (ctrl.recado === texto) { ctrl.recado = ''; pintar(); } }, 6000);
  }

  const RECADOS = {
    'not-allowed': 'Permissão de microfone negada — libere no cadeado da barra de endereço.',
    'service-not-allowed': 'O navegador bloqueou o reconhecimento de fala.',
    'audio-capture': 'Nenhum microfone encontrado.',
    'network': 'Sem rede para o reconhecimento de fala.',
  };

  function criarRec() {
    const rec = new Fala();
    rec.lang = 'pt-BR';
    rec.continuous = ctrl.continuo;
    rec.interimResults = false;
    rec.maxAlternatives = 1;

    // `rodando` vem do próprio reconhecimento, não da nossa intenção: era a
    // dessincronia entre os dois que fazia o botão dizer "Ouvindo" com o
    // microfone desligado, sem nada na tela explicando.
    rec.onstart = () => { ctrl.rodando = true; ctrl.partindo = false; pintar(); };
    rec.onend = () => {
      ctrl.rodando = false;
      ctrl.partindo = false;
      if (ctrl.querendo) W.setTimeout(arrancar, 250); else pintar();
    };

    rec.onresult = (ev) => {
      const r = ev.results[ev.results.length - 1];
      if (!r.isFinal) return;
      const texto = (r[0].transcript || '').trim();
      if (!texto) return;
      if (ctrl.continuo && !chamaram(texto)) return;
      enviar(texto);
      if (!ctrl.continuo) parar();
    };

    rec.onerror = (ev) => {
      if (ev.error === 'aborted') return;              // nós mesmos paramos
      if (ev.error === 'no-speech') {
        if (!ctrl.continuo) { ctrl.querendo = false; recadar('Não ouvi nada — clique e fale.'); }
        return;
      }
      ctrl.querendo = false;
      if (ev.error === 'not-allowed' && embutido) {
        recadar('Abra o app na própria aba: embutido em outra página o '
                + 'navegador não libera o microfone.');
        return;
      }
      recadar(RECADOS[ev.error] || ('Falha no microfone: ' + ev.error));
    };
    return rec;
  }

  // Sempre um objeto novo: o SpeechRecognition do Chrome fica inutilizável
  // depois de certos erros, e reaproveitá-lo era o que deixava o microfone
  // morto sem nenhum sinal — clicava, e nada.
  function arrancar() {
    if (!ctrl.querendo || ctrl.rodando || ctrl.partindo) return;
    ctrl.partindo = true;
    ctrl.rec = criarRec();
    try {
      ctrl.rec.start();
    } catch (err) {
      ctrl.partindo = false;
      // a sessão anterior ainda está encerrando; o onend dela chama de novo
      if (err && err.name === 'InvalidStateError') return;
      ctrl.querendo = false;
      recadar('Não consegui abrir o microfone: ' + (err && err.message || err));
    }
  }

  function iniciar() {
    if (!Fala) return;
    // fora de HTTPS o Chrome nem chega a perguntar pela permissão
    if (!W.isSecureContext) { recadar('O microfone só funciona em HTTPS.'); return; }
    ctrl.recado = '';
    ctrl.querendo = true;
    arrancar();
    pintar();
  }

  function parar() {
    ctrl.querendo = false;
    if (ctrl.rec) { try { ctrl.rec.stop(); } catch (err) {} }
    pintar();
  }

  // O Streamlit redesenha o slot a cada rerun e leva o botão junto. O iframe
  // que instalou este script nem sempre reexecuta, então esperar por ele para
  // remontar era apostar — e o botão sumia. Uma vigia curta (lá embaixo) torna
  // a remontagem independente do que o Streamlit decidir refazer: o
  // reconhecimento, esse, nunca reinicia, porque mora aqui e não no botão.
  function montar() {
    const slot = D.getElementById('voz-slot');
    if (!slot || slot.contains(ctrl.botao)) { pintar(); return; }

    slot.textContent = '';
    ctrl.botao = D.createElement('button');
    ctrl.botao.type = 'button';
    ctrl.botao.className = 'voz-botao';
    ctrl.botao.disabled = !Fala;
    ctrl.botao.onclick = () => (ctrl.querendo ? parar() : iniciar());

    ctrl.status = D.createElement('span');
    ctrl.status.className = 'voz-status';

    slot.appendChild(ctrl.botao);
    slot.appendChild(ctrl.status);
    ctrl.recado = '';
    pintar();
  }

  W.__acervoVoz = {
    montar,
    modo: (continuo) => {
      if (continuo === ctrl.continuo) return;
      ctrl.continuo = continuo;
      // `continuous` só vale no start; para valer agora, a sessão recomeça
      if (ctrl.querendo) { parar(); W.setTimeout(iniciar, 300); }
    },
    // usado pelos testes de interface: injeta uma frase sem passar pelo microfone
    dizer: enviar,
    estado: () => ({ querendo: ctrl.querendo, rodando: ctrl.rodando, recado: ctrl.recado }),
  };

  // Registrada aqui, a vigia é da página e vive enquanto a aba viver — nenhum
  // rerun a alcança. (Enquanto ela morava no iframe, cada troca de iframe
  // descartava o realm que a registrou e o botão ficava órfão.)
  if (W.__acervoVozVigia) W.clearInterval(W.__acervoVozVigia);
  W.__acervoVozVigia = W.setInterval(montar, 400);
  montar();
})();
"""

# Roda dentro do iframe, e faz uma coisa só: pôr o controlador para rodar na
# página. `script.textContent` executa de forma síncrona no append, então
# `__acervoVoz` já existe na linha seguinte.
_PONTE_JS = """
<script>
(function () {
  const W = window.parent, D = W.document;
  if (!W.__acervoVoz) {
    const script = D.createElement('script');
    script.id = 'acervo-voz-controlador';
    script.textContent = __CONTROLADOR__;
    D.head.appendChild(script);
  }
  // A caixa "escuta contínua" mudou o script; esta é a única via de a mudança
  // chegar até um controlador que já está de pé.
  if (W.__acervoVoz) { W.__acervoVoz.modo(__CONTINUO__); W.__acervoVoz.montar(); }
})();
</script>
"""


def _injetar_ponte() -> None:
    controlador = _CONTROLADOR_JS.replace("__ATIVACOES__", json.dumps(list(cmd.ATIVACOES)))
    script = (
        _PONTE_JS
        # json.dumps: o controlador vira um literal de string JS, e nenhum
        # acento, aspa ou `\\u` dele precisa de escape manual
        .replace("__CONTROLADOR__", json.dumps(controlador))
        .replace("__CONTINUO__", "true" if st.session_state.get(ESCUTA_CONTINUA) else "false")
    )
    # altura 1: o iframe é só um instalador de script, não tem o que mostrar;
    # o CSS do tema esconde o espaço que o Streamlit reserva para ele.
    st.iframe(script, height=1)


_CORES_BADGE = {
    "ok": "voz-ok", "aviso": "voz-aviso", "erro": "voz-erro",
    "ajuda": "voz-ok", "saudacao": "voz-ok",
}


def painel() -> None:
    """A barra do assistente: microfone, campo de comando e confirmação."""
    with st.container(key="voz_painel"):
        col_mic, col_campo, col_ajuda = st.columns(
            [1.15, 3.4, 0.75], vertical_alignment="center",
        )

        # o botão do microfone é criado pelo JS e encaixado aqui — ele precisa
        # sobreviver ao rerun, e um st.button não sobrevive
        col_mic.markdown('<div id="voz-slot" class="voz-slot"></div>', unsafe_allow_html=True)

        col_campo.text_input(
            "Comando de voz",
            key=COMANDO,
            placeholder="Comece pelo nome: “Luiz, como fazer um group by no pandas”…",
            label_visibility="collapsed",
            on_change=_receber,
        )

        with col_ajuda.popover("Comandos", width="stretch"):
            st.markdown(
                '<span class="card-meta">Toda frase começa por <b>“Luiz”</b> — falada '
                'ou digitada. Pergunte com as suas palavras: o que não for um dos '
                'comandos abaixo vira busca no acervo.</span>',
                unsafe_allow_html=True,
            )
            for grupo, frases in cmd.EXEMPLOS:
                st.markdown(f"**{grupo}**")
                st.markdown(
                    "".join(f'<div class="voz-exemplo">“{frase}”</div>' for frase in frases),
                    unsafe_allow_html=True,
                )
            st.checkbox(
                "Escuta contínua",
                key=ESCUTA_CONTINUA,
                help="Deixa o microfone sempre aberto. Como toda frase precisa "
                     "começar por “Luiz”, a conversa em volta não vira comando.",
            )

        ultimo = st.session_state.get(ULTIMO)
        if ultimo:
            nivel, mensagem = ultimo
            classe = _CORES_BADGE.get(nivel, "voz-aviso")
            # `mensagem` carrega o que a pessoa falou, e o badge é HTML cru:
            # sem escapar, uma transcrição com "<" come o resto da barra
            st.markdown(
                f'<div class="voz-badge {classe}">{html.escape(mensagem)}</div>',
                unsafe_allow_html=True,
            )
        if ultimo and ultimo[0] == "ajuda":
            _ajuda_expandida()

        _injetar_ponte()


def _ajuda_expandida() -> None:
    """A ajuda pedida por voz — quem falou "ajuda" não vai clicar no popover."""
    colunas = st.columns(3)
    for i, (grupo, frases) in enumerate(cmd.EXEMPLOS):
        with colunas[i % 3]:
            st.markdown(f"**{grupo}**")
            st.markdown(
                "".join(f'<div class="voz-exemplo">“{frase}”</div>' for frase in frases),
                unsafe_allow_html=True,
            )


def indice_para_abrir(total: int) -> Optional[int]:
    """O índice (base 0) que a busca deve abrir agora, se houver.

    Consome o pedido: um rerun por qualquer outro motivo não pode reabrir o
    diálogo que a pessoa acabou de fechar.
    """
    pedido = st.session_state.pop(ABRIR_INDICE, None)
    if pedido is None:
        return None
    if total <= 0:
        st.session_state[ULTIMO] = ("aviso", "Não há resultados abertos para abrir.")
        return None
    posicao = total if pedido == -1 else int(pedido)
    if posicao < 1 or posicao > total:
        st.session_state[ULTIMO] = (
            "aviso", f"Só há {total} resultado(s) nesta página."
        )
        return None
    return posicao - 1


def descartar_abertura(motivo: str) -> None:
    """Sem lista de resultados na tela, "abrir o terceiro" não tem alvo.

    O pedido precisa ser consumido de qualquer jeito: deixá-lo no estado faria
    o diálogo abrir sozinho na próxima busca, muitos comandos depois.
    """
    if st.session_state.pop(ABRIR_INDICE, None) is not None:
        st.session_state[ULTIMO] = ("aviso", motivo)
