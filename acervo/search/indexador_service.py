"""Orquestra a indexação: varre os arquivos, chama o parser certo para cada
um e grava o resultado no banco.

Contrato de robustez (o motivo desta camada existir): a falha de UM arquivo
— parser que não entende o formato, encoding quebrado, erro do banco ao
gravar aquele arquivo específico — nunca interrompe o lote inteiro. Ela é
isolada, logada, registrada na tabela de falhas, e a indexação segue para o
próximo arquivo. Só um erro de configuração (ex.: categorias.json ausente)
é fatal, porque sem isso não há o que indexar.
"""
import logging
from typing import Optional

from acervo.core.exceptions import AcervoError, ArquivoParseError
from acervo.core.models import Arquivo, Bloco, Categoria
from acervo.ingestion import scanner
from acervo.ingestion.parsers import notebook_parser, pdf_parser, pptx_parser, sql_parser, text_parser
from acervo.persistence.db import cursor
from acervo.persistence.repository import (
    ArquivoRepository,
    BlocoRepository,
    CategoriaRepository,
    FalhaRepository,
)

logger = logging.getLogger("acervo.indexador")

_PARSERS = {
    "notebook": notebook_parser.parse,
    "sql": sql_parser.parse,
    "texto": text_parser.parse,
    "pdf": pdf_parser.parse,
    "pptx": pptx_parser.parse,
}

# Postgres rejeita bytes NUL em colunas de texto, e a coluna gerada
# `texto_busca` (tsvector) tem um limite duro de ~1MB somando os três
# campos. Alguns .txt do acervo são, na prática, dumps de dados (não
# "conteúdo" para estudar) e passam bem desse limite — em vez de descartar
# o arquivo inteiro, truncamos o texto para caber com folga.
_LIMITE_CAMPO_TEXTO = 50_000


def _sanitizar_texto(texto: Optional[str]) -> Optional[str]:
    if texto is None:
        return None
    texto = texto.replace("\x00", "")
    if len(texto) > _LIMITE_CAMPO_TEXTO:
        texto = texto[:_LIMITE_CAMPO_TEXTO] + "\n[... conteúdo truncado ...]"
    return texto


class _PulaArquivoSemAlteracao(Exception):
    """Sinaliza internamente que o arquivo não mudou desde a última indexação."""


class ResultadoIndexacao:
    def __init__(self) -> None:
        self.processados = 0
        self.pulados_sem_alteracao = 0
        self.ignorados_tipo = 0
        self.falhas = 0

    def __repr__(self) -> str:
        return (
            f"ResultadoIndexacao(processados={self.processados}, "
            f"pulados_sem_alteracao={self.pulados_sem_alteracao}, "
            f"ignorados_tipo={self.ignorados_tipo}, falhas={self.falhas})"
        )


def indexar_tudo(
    schema: str = "acervo",
    *,
    raiz=None,
    categorias_repo: Optional[CategoriaRepository] = None,
    arquivos_repo: Optional[ArquivoRepository] = None,
    blocos_repo: Optional[BlocoRepository] = None,
    falhas_repo: Optional[FalhaRepository] = None,
) -> ResultadoIndexacao:
    categorias_repo = categorias_repo or CategoriaRepository(schema)
    arquivos_repo = arquivos_repo or ArquivoRepository(schema)
    blocos_repo = blocos_repo or BlocoRepository(schema)
    falhas_repo = falhas_repo or FalhaRepository(schema)

    categoria_id_por_pasta: dict[str, int] = {}
    with cursor() as cur:
        for pasta_raiz, meta in scanner.carregar_categorias().items():
            categoria_id_por_pasta[pasta_raiz] = categorias_repo.upsert(cur, Categoria(
                id=None,
                nome=meta["categoria"],
                subcategoria=meta.get("subcategoria"),
                cor=meta["cor"],
                pasta_raiz=pasta_raiz,
            ))

    resultado = ResultadoIndexacao()
    arquivos_iter = scanner.listar_arquivos(raiz) if raiz is not None else scanner.listar_arquivos()

    for arquivo_bruto in arquivos_iter:
        if arquivo_bruto.tipo_parser is None:
            resultado.ignorados_tipo += 1
            continue

        try:
            _indexar_um_arquivo(arquivo_bruto, categoria_id_por_pasta, arquivos_repo, blocos_repo)
            resultado.processados += 1
        except _PulaArquivoSemAlteracao:
            resultado.pulados_sem_alteracao += 1
        except ArquivoParseError as e:
            resultado.falhas += 1
            logger.warning("Falha ao processar %s: %s", arquivo_bruto.caminho_relativo, e)
            _registrar_falha_isolada(falhas_repo, arquivo_bruto.caminho_relativo, e.etapa, str(e.causa))
        except AcervoError as e:
            resultado.falhas += 1
            logger.error("Erro de infraestrutura ao processar %s: %s", arquivo_bruto.caminho_relativo, e)
            _registrar_falha_isolada(falhas_repo, arquivo_bruto.caminho_relativo, "infraestrutura", str(e))
        except Exception as e:  # rede de segurança: nenhum arquivo pode travar o lote
            resultado.falhas += 1
            logger.exception("Erro inesperado ao processar %s", arquivo_bruto.caminho_relativo)
            _registrar_falha_isolada(falhas_repo, arquivo_bruto.caminho_relativo, "desconhecida", str(e))

    logger.info("Indexação concluída: %s", resultado)
    return resultado


def _indexar_um_arquivo(arquivo_bruto, categoria_id_por_pasta, arquivos_repo, blocos_repo) -> None:
    with cursor() as cur:
        ja_indexado = arquivos_repo.hash_ja_indexado(cur, arquivo_bruto.caminho_relativo, arquivo_bruto.hash)
    if ja_indexado:
        raise _PulaArquivoSemAlteracao()

    # parsing acontece fora de qualquer transação: é a parte lenta/CPU-bound
    # e não deve segurar uma conexão do pool enquanto roda
    parser_fn = _PARSERS[arquivo_bruto.tipo_parser]
    blocos_brutos = parser_fn(arquivo_bruto.caminho_absoluto)

    with cursor() as cur:
        arquivo_id = arquivos_repo.upsert(cur, Arquivo(
            id=None,
            caminho=arquivo_bruto.caminho_relativo,
            categoria_id=categoria_id_por_pasta[arquivo_bruto.pasta_raiz],
            extensao=arquivo_bruto.extensao,
            tipo="conteudo",
            tamanho_bytes=arquivo_bruto.tamanho_bytes,
            hash=arquivo_bruto.hash,
            duplicado_de=None,
        ))
        arquivos_repo.remover_blocos(cur, arquivo_id)
        blocos_repo.inserir_muitos(cur, [
            Bloco(
                id=None,
                arquivo_id=arquivo_id,
                ordem=b.ordem,
                titulo=_sanitizar_texto(b.titulo),
                explicacao=_sanitizar_texto(b.explicacao),
                codigo=_sanitizar_texto(b.codigo),
                linguagem=b.linguagem,
            )
            for b in blocos_brutos
        ])


def _registrar_falha_isolada(falhas_repo: FalhaRepository, caminho: str, etapa: str, erro: str) -> None:
    try:
        with cursor() as cur:
            falhas_repo.registrar(cur, caminho, etapa, erro)
    except AcervoError:
        logger.error("Não foi possível registrar a falha de '%s' no banco (banco indisponível?)", caminho)
