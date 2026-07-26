"""Repositórios — única camada que conhece SQL.

Cada método recebe o `cur` (cursor já aberto) explicitamente em vez de abrir
sua própria conexão. Isso permite que o chamador (o serviço de indexação)
controle a fronteira da transação: várias operações do mesmo arquivo (upsert
do arquivo + troca dos blocos) acontecem dentro de um único `with cursor()`,
então uma falha no meio desfaz tudo daquele arquivo (rollback), sem afetar
os demais.

O nome do schema é sempre um valor fixo definido pelo código (nunca vindo de
input externo/usuário), então interpolá-lo no identificador SQL via f-string
é seguro — os *valores* das colunas sempre vão como parâmetro (%s).
"""
from typing import Optional, Sequence

from acervo.core.models import (
    Arquivo,
    Bloco,
    Categoria,
    ConteudoCategoria,
    EstatisticaCategoria,
    ResultadoBusca,
    ResumoAcervo,
)


class CategoriaRepository:
    def __init__(self, schema: str = "acervo"):
        self.schema = schema

    def upsert(self, cur, categoria: Categoria) -> int:
        cur.execute(
            f'INSERT INTO "{self.schema}".categorias (nome, subcategoria, cor, pasta_raiz) '
            f'VALUES (%s, %s, %s, %s) '
            f'ON CONFLICT (pasta_raiz) DO UPDATE SET '
            f'nome = EXCLUDED.nome, subcategoria = EXCLUDED.subcategoria, cor = EXCLUDED.cor '
            f'RETURNING id',
            (categoria.nome, categoria.subcategoria, categoria.cor, categoria.pasta_raiz),
        )
        return cur.fetchone()[0]


class ArquivoRepository:
    def __init__(self, schema: str = "acervo"):
        self.schema = schema

    def hash_ja_indexado(self, cur, caminho: str, hash_: str) -> bool:
        cur.execute(
            f'SELECT 1 FROM "{self.schema}".arquivos WHERE caminho = %s AND hash = %s',
            (caminho, hash_),
        )
        return cur.fetchone() is not None

    def upsert(self, cur, arquivo: Arquivo) -> int:
        cur.execute(
            f'INSERT INTO "{self.schema}".arquivos '
            f'(caminho, categoria_id, extensao, tipo, tamanho_bytes, hash, origem, atualizado_em) '
            f'VALUES (%s, %s, %s, %s, %s, %s, %s, now()) '
            f'ON CONFLICT (caminho) DO UPDATE SET '
            f'categoria_id = EXCLUDED.categoria_id, extensao = EXCLUDED.extensao, '
            f'tipo = EXCLUDED.tipo, tamanho_bytes = EXCLUDED.tamanho_bytes, '
            f'hash = EXCLUDED.hash, origem = EXCLUDED.origem, atualizado_em = now() '
            f'RETURNING id',
            (arquivo.caminho, arquivo.categoria_id, arquivo.extensao,
             arquivo.tipo, arquivo.tamanho_bytes, arquivo.hash, arquivo.origem),
        )
        return cur.fetchone()[0]

    def remover_blocos(self, cur, arquivo_id: int) -> None:
        cur.execute(f'DELETE FROM "{self.schema}".blocos WHERE arquivo_id = %s', (arquivo_id,))

    def hash_por_caminho(self, cur, caminho: str) -> Optional[str]:
        cur.execute(f'SELECT hash FROM "{self.schema}".arquivos WHERE caminho = %s', (caminho,))
        linha = cur.fetchone()
        return linha[0] if linha else None

    def caminho_com_hash(self, cur, hash_: str) -> Optional[str]:
        """Caminho de algum arquivo já indexado com este hash (detecção de duplicata)."""
        cur.execute(
            f'SELECT caminho FROM "{self.schema}".arquivos WHERE hash = %s LIMIT 1',
            (hash_,),
        )
        linha = cur.fetchone()
        return linha[0] if linha else None

    def listar_caminhos_de_varredura(self, cur, pasta_raiz: str) -> list[str]:
        """Caminhos vindos da varredura de disco para uma pasta raiz.

        Uploads (origem = 'upload') ficam de fora de propósito: eles existem
        apenas no banco e nunca participam da reconciliação com o disco.
        """
        cur.execute(
            f'SELECT a.caminho FROM "{self.schema}".arquivos a '
            f'JOIN "{self.schema}".categorias c ON c.id = a.categoria_id '
            f"WHERE c.pasta_raiz = %s AND a.origem = 'varredura'",
            (pasta_raiz,),
        )
        return [linha[0] for linha in cur.fetchall()]

    def remover_por_caminhos(self, cur, caminhos: Sequence[str]) -> int:
        """Remove arquivos (e seus blocos, via ON DELETE CASCADE) pelos caminhos."""
        if not caminhos:
            return 0
        cur.execute(
            f'DELETE FROM "{self.schema}".arquivos WHERE caminho = ANY(%s)',
            (list(caminhos),),
        )
        return cur.rowcount

    def contar(self, cur) -> int:
        cur.execute(f'SELECT count(*) FROM "{self.schema}".arquivos')
        return cur.fetchone()[0]


class BlocoRepository:
    def __init__(self, schema: str = "acervo"):
        self.schema = schema

    def inserir_muitos(self, cur, blocos: Sequence[Bloco]) -> None:
        if not blocos:
            return
        cur.executemany(
            f'INSERT INTO "{self.schema}".blocos '
            f'(arquivo_id, ordem, titulo, explicacao, codigo, linguagem) '
            f'VALUES (%s, %s, %s, %s, %s, %s) '
            f'ON CONFLICT (arquivo_id, ordem) DO UPDATE SET '
            f'titulo = EXCLUDED.titulo, explicacao = EXCLUDED.explicacao, '
            f'codigo = EXCLUDED.codigo, linguagem = EXCLUDED.linguagem',
            [(b.arquivo_id, b.ordem, b.titulo, b.explicacao, b.codigo, b.linguagem) for b in blocos],
        )


class BuscaRepository:
    """Consultas de leitura da busca (Fase 2).

    As duas variantes devolvem o mesmo formato (`ResultadoBusca` + total geral
    via janela `count(*) OVER ()`), o que permite à camada de serviço e à UI
    tratá-las de forma idêntica:

      - `buscar_texto`: full-text search em português sobre `texto_busca`
        (título + explicação + código), com stemming ("consultas" encontra
        "consulta") e ranking por `ts_rank`. Usa `websearch_to_tsquery`, que
        nunca levanta erro de sintaxe para input do usuário.
      - `buscar_codigo`: busca literal de trecho de código via ILIKE (coberta
        pelo índice trigram `idx_blocos_codigo_trgm`), ordenada por
        `similarity`. É o caminho certo para termos como "df.groupby" ou
        "pg_settings", que o stemming do full-text quebraria.
    """

    _SELECT_BASE = (
        'SELECT b.id, a.caminho, c.nome, c.subcategoria, '
        'b.titulo, b.explicacao, b.codigo, b.linguagem, '
        '{relevancia} AS relevancia, count(*) OVER () AS total '
        'FROM "{schema}".blocos b '
        'JOIN "{schema}".arquivos a ON a.id = b.arquivo_id '
        'JOIN "{schema}".categorias c ON c.id = a.categoria_id '
    )

    def __init__(self, schema: str = "acervo"):
        self.schema = schema

    def buscar_texto(
        self,
        cur,
        termo: str,
        *,
        categoria_id: Optional[int] = None,
        linguagem: Optional[str] = None,
        arquivo_caminho: Optional[str] = None,
        limite: int = 20,
        offset: int = 0,
    ) -> tuple[list[ResultadoBusca], int]:
        filtros, params_filtros = self._montar_filtros(categoria_id, linguagem, arquivo_caminho)
        # mesma configuração usada na coluna texto_busca (migração 0002):
        # unaccent + stemming português nos dois lados da comparação
        config = f"{self.schema}.portugues_unaccent"
        sql = (
            self._SELECT_BASE.format(schema=self.schema, relevancia="ts_rank(b.texto_busca, query)")
            + ", websearch_to_tsquery(%s::regconfig, %s) query "
            + "WHERE b.texto_busca @@ query" + filtros
            + " ORDER BY relevancia DESC, b.id LIMIT %s OFFSET %s"
        )
        cur.execute(sql, (config, termo, *params_filtros, limite, offset))
        return self._mapear(cur.fetchall())

    def buscar_codigo(
        self,
        cur,
        trecho: str,
        *,
        categoria_id: Optional[int] = None,
        linguagem: Optional[str] = None,
        arquivo_caminho: Optional[str] = None,
        limite: int = 20,
        offset: int = 0,
    ) -> tuple[list[ResultadoBusca], int]:
        filtros, params_filtros = self._montar_filtros(categoria_id, linguagem, arquivo_caminho)
        # escapa curingas do LIKE para que "100%" busque o texto literal "100%"
        escapado = trecho.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql = (
            self._SELECT_BASE.format(schema=self.schema, relevancia="similarity(b.codigo, %s)")
            + "WHERE b.codigo ILIKE %s" + filtros
            + " ORDER BY relevancia DESC, b.id LIMIT %s OFFSET %s"
        )
        cur.execute(sql, (trecho, f"%{escapado}%", *params_filtros, limite, offset))
        return self._mapear(cur.fetchall())

    def blocos_do_arquivo(self, cur, arquivo_caminho: str) -> list[Bloco]:
        """Conteúdo completo de um arquivo, na ordem original — para a tela de detalhe."""
        cur.execute(
            f'SELECT b.id, b.arquivo_id, b.ordem, b.titulo, b.explicacao, b.codigo, b.linguagem '
            f'FROM "{self.schema}".blocos b '
            f'JOIN "{self.schema}".arquivos a ON a.id = b.arquivo_id '
            f'WHERE a.caminho = %s ORDER BY b.ordem',
            (arquivo_caminho,),
        )
        return [Bloco(*linha) for linha in cur.fetchall()]

    def listar_categorias(self, cur) -> list[Categoria]:
        cur.execute(
            f'SELECT id, nome, subcategoria, cor, pasta_raiz '
            f'FROM "{self.schema}".categorias ORDER BY nome'
        )
        return [Categoria(*linha) for linha in cur.fetchall()]

    def listar_linguagens(self, cur) -> list[str]:
        cur.execute(
            f'SELECT DISTINCT linguagem FROM "{self.schema}".blocos '
            f'WHERE linguagem IS NOT NULL ORDER BY linguagem'
        )
        return [linha[0] for linha in cur.fetchall()]

    def listar_conteudos(self, cur, categoria_id: int) -> list[ConteudoCategoria]:
        """Arquivos de uma categoria que têm conteúdo indexado.

        Alimenta o filtro dependente da UI: escolhida a categoria (ex.: o livro
        de Estatística), estes são os assuntos/arquivos que existem dentro dela.
        O `JOIN` com blocos (em vez de `LEFT JOIN`) já descarta arquivos de
        dados e os que falharam na extração — filtrar por eles não traria
        resultado nenhum.
        """
        cur.execute(
            f'SELECT a.caminho, c.pasta_raiz, count(b.id) AS total_blocos '
            f'FROM "{self.schema}".arquivos a '
            f'JOIN "{self.schema}".categorias c ON c.id = a.categoria_id '
            f'JOIN "{self.schema}".blocos b ON b.arquivo_id = a.id '
            f'WHERE a.categoria_id = %s '
            f'GROUP BY a.caminho, c.pasta_raiz '
            f'ORDER BY a.caminho',
            (categoria_id,),
        )
        return [ConteudoCategoria(*linha) for linha in cur.fetchall()]

    @staticmethod
    def _montar_filtros(
        categoria_id: Optional[int],
        linguagem: Optional[str],
        arquivo_caminho: Optional[str] = None,
    ) -> tuple[str, list]:
        filtros = ""
        params: list = []
        if categoria_id is not None:
            filtros += " AND c.id = %s"
            params.append(categoria_id)
        if linguagem is not None:
            filtros += " AND b.linguagem = %s"
            params.append(linguagem)
        if arquivo_caminho is not None:
            filtros += " AND a.caminho = %s"
            params.append(arquivo_caminho)
        return filtros, params

    @staticmethod
    def _mapear(linhas) -> tuple[list[ResultadoBusca], int]:
        total = linhas[0][-1] if linhas else 0
        return [ResultadoBusca(*linha[:-1]) for linha in linhas], total


class EstatisticaRepository:
    """Números agregados do acervo — alimenta o dashboard (Fase 3)."""

    def __init__(self, schema: str = "acervo"):
        self.schema = schema

    def resumo(self, cur) -> ResumoAcervo:
        cur.execute(
            f'SELECT (SELECT count(*) FROM "{self.schema}".arquivos), '
            f'(SELECT count(*) FROM "{self.schema}".blocos), '
            f'(SELECT count(*) FROM "{self.schema}".falhas_indexacao)'
        )
        total_arquivos, total_blocos, total_falhas = cur.fetchone()

        cur.execute(
            f'SELECT c.nome, c.subcategoria, c.cor, '
            f'count(DISTINCT a.id) AS total_arquivos, count(b.id) AS total_blocos '
            f'FROM "{self.schema}".categorias c '
            f'LEFT JOIN "{self.schema}".arquivos a ON a.categoria_id = c.id '
            f'LEFT JOIN "{self.schema}".blocos b ON b.arquivo_id = a.id '
            f'GROUP BY c.nome, c.subcategoria, c.cor '
            f'ORDER BY total_arquivos DESC, c.nome'
        )
        por_categoria = tuple(EstatisticaCategoria(*linha) for linha in cur.fetchall())

        return ResumoAcervo(
            total_arquivos=total_arquivos,
            total_blocos=total_blocos,
            total_falhas=total_falhas,
            por_categoria=por_categoria,
        )


class FalhaRepository:
    def __init__(self, schema: str = "acervo"):
        self.schema = schema

    def registrar(self, cur, arquivo_caminho: str, etapa: str, erro: str) -> None:
        cur.execute(
            f'INSERT INTO "{self.schema}".falhas_indexacao (arquivo_caminho, etapa, erro) '
            f'VALUES (%s, %s, %s)',
            (arquivo_caminho, etapa, erro),
        )
