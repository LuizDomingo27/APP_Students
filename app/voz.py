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
      → rerun → `processar_pendente` interpreta e executa  [_executar]

O campo de texto no meio não é gambiarra: é a única via oficial de um script
do navegador devolver texto para o Python sem construir um componente React
com build próprio. E ele é também a interface de fallback — dá para digitar
os mesmos comandos, o que torna o assistente testável e utilizável em
navegador sem reconhecimento de fala.

## O controlador vive na página, não no iframe

`components.html` cria um iframe novo a cada rerun; um reconhecimento de fala
que morasse lá dentro morreria a cada comando executado. Então o iframe é só
um instalador: ele injeta o controlador na página principal, onde `window`
sobrevive aos reruns, e nas vezes seguintes apenas reencaixa o botão no lugar
que o Streamlit acabou de redesenhar.
"""
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


def _fazer_buscar(comando: cmd.Comando) -> tuple[str, str]:
    _ir_para(cmd.PAGINA_BUSCA)
    st.session_state[_TERMO] = comando.valor
    st.session_state[_PAGINA] = 1
    return "ok", comando.descricao


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


def _fazer_limpar(acao: str) -> tuple[str, str]:
    if acao in (cmd.LIMPAR_BUSCA, cmd.LIMPAR_TUDO):
        st.session_state[_TERMO] = ""
        st.session_state[_PAGINA] = 1
    if acao in (cmd.LIMPAR_FILTROS, cmd.LIMPAR_TUDO):
        st.session_state[_CATEGORIA] = comp.FILTRO_TODAS
        st.session_state[_CONTEUDO] = comp.FILTRO_TODO_CONTEUDO
        st.session_state[_LINGUAGEM] = comp.FILTRO_TODAS
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
    """Executa a frase que chegou. Chamar no topo do run, antes dos widgets."""
    frase = st.session_state.pop(PENDENTE, None)
    if not frase:
        return

    comando = cmd.interpretar(frase)
    if comando is None:
        st.session_state[ULTIMO] = (
            "aviso", f"Não entendi “{frase}”. Diga “ajuda” para ver os comandos."
        )
        return

    nivel, mensagem = _executar(comando, eh_admin=eh_admin)
    st.session_state[ULTIMO] = (nivel, mensagem)

    if nivel == "sair":
        from app import sessao  # import local: `sessao` não é usado em mais nada aqui
        sessao.encerrar_sessao()
        st.rerun()


# ------------------------------------------------------------------- ponte JS
# Instalado uma vez na página principal; nos reruns seguintes só reencaixa o
# botão. Ver a nota "O controlador vive na página" no topo do módulo.

_PONTE_JS = """
<script>
(function () {
  const W = window.parent, D = W.document;
  const ATIVACOES = __ATIVACOES__;

  if (W.__acervoVoz) { W.__acervoVoz.montar(); return; }

  const Fala = W.SpeechRecognition || W.webkitSpeechRecognition;
  const ctrl = {
    ligado: false,
    continuo: __CONTINUO__,
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
  function enviar(texto) {
    const alvo = campo();
    if (!alvo) return;
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
      .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').trim()
      .replace(/^(ok|ei|oi|hey)\\s+/, '');
    return ATIVACOES.some(p => limpo.startsWith(p));
  }

  function pintar() {
    if (!ctrl.botao) return;
    ctrl.botao.classList.toggle('ouvindo', ctrl.ligado);
    ctrl.botao.textContent = ctrl.ligado ? '● Ouvindo' : '🎙 Falar';
    ctrl.botao.title = ctrl.ligado ? 'Parar de ouvir' : 'Começar a ouvir';
    if (ctrl.status) {
      ctrl.status.textContent = !Fala
        ? 'Este navegador não reconhece fala — use o campo ao lado.'
        : ctrl.ligado
          ? (ctrl.continuo ? 'Diga “assistente…” antes do comando.' : 'Pode falar.')
          : '';
    }
  }

  function criarRec() {
    const rec = new Fala();
    rec.lang = 'pt-BR';
    rec.continuous = ctrl.continuo;
    rec.interimResults = false;
    rec.maxAlternatives = 1;

    rec.onresult = (ev) => {
      const r = ev.results[ev.results.length - 1];
      if (!r.isFinal) return;
      const texto = (r[0].transcript || '').trim();
      if (!texto) return;
      if (ctrl.continuo && !chamaram(texto)) return;
      enviar(texto);
      if (!ctrl.continuo) parar();
    };
    // 'no-speech' e 'aborted' são o silêncio normal entre um comando e outro;
    // só desligam o botão os erros que a pessoa precisa resolver.
    rec.onerror = (ev) => {
      if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
        ctrl.ligado = false;
        if (ctrl.status) ctrl.status.textContent = 'Permissão de microfone negada.';
        pintar();
      }
    };
    rec.onend = () => { if (ctrl.ligado) { try { rec.start(); } catch (e) {} } };
    return rec;
  }

  function iniciar() {
    if (!Fala) return;
    ctrl.rec = ctrl.rec || criarRec();
    ctrl.rec.continuous = ctrl.continuo;
    ctrl.ligado = true;
    try { ctrl.rec.start(); } catch (e) {}
    pintar();
  }

  function parar() {
    ctrl.ligado = false;
    if (ctrl.rec) { try { ctrl.rec.stop(); } catch (e) {} }
    pintar();
  }

  // O Streamlit redesenha o slot a cada rerun; o botão é reencaixado nele,
  // mas o reconhecimento (e o fato de estar ligado) nunca reinicia.
  function montar(tentativa) {
    const slot = D.getElementById('voz-slot');
    if (!slot) {
      if ((tentativa || 0) < 40) W.setTimeout(() => montar((tentativa || 0) + 1), 50);
      return;
    }
    if (slot.contains(ctrl.botao)) { pintar(); return; }

    slot.textContent = '';
    ctrl.botao = D.createElement('button');
    ctrl.botao.type = 'button';
    ctrl.botao.className = 'voz-botao';
    ctrl.botao.disabled = !Fala;
    ctrl.botao.onclick = () => (ctrl.ligado ? parar() : iniciar());

    ctrl.status = D.createElement('span');
    ctrl.status.className = 'voz-status';

    slot.appendChild(ctrl.botao);
    slot.appendChild(ctrl.status);
    pintar();
  }

  W.__acervoVoz = {
    montar,
    modo: (continuo) => {
      ctrl.continuo = continuo;
      if (ctrl.ligado) { parar(); iniciar(); }
    },
    // usado pelos testes de interface: injeta uma frase sem passar pelo microfone
    dizer: enviar,
  };
  montar();
})();
</script>
"""


def _injetar_ponte() -> None:
    import json

    script = (
        _PONTE_JS
        .replace("__ATIVACOES__", json.dumps(list(cmd.ATIVACOES)))
        .replace("__CONTINUO__", "true" if st.session_state.get(ESCUTA_CONTINUA) else "false")
    )
    # altura 1: o iframe é só um instalador de script, não tem o que mostrar;
    # o CSS do tema esconde o espaço que o Streamlit reserva para ele.
    st.iframe(script, height=1)


_CORES_BADGE = {"ok": "voz-ok", "aviso": "voz-aviso", "erro": "voz-erro", "ajuda": "voz-ok"}


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
            placeholder="Fale ou digite um comando: “ir para o dashboard”, “buscar regressão”…",
            label_visibility="collapsed",
            on_change=_receber,
        )

        with col_ajuda.popover("Comandos", width="stretch"):
            st.markdown(
                '<span class="card-meta">Fale ou digite qualquer uma destas frases. '
                'Com a escuta contínua ligada, comece por <b>“assistente…”</b>.</span>',
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
                help="Deixa o microfone sempre aberto; só executa frases que comecem "
                     "por “assistente”, “computador” ou “acervo”.",
            )

        ultimo = st.session_state.get(ULTIMO)
        if ultimo:
            nivel, mensagem = ultimo
            classe = _CORES_BADGE.get(nivel, "voz-aviso")
            st.markdown(
                f'<div class="voz-badge {classe}">{mensagem}</div>',
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
