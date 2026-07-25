"""Adiciona conteúdo ao acervo a partir da interface (upload de arquivo).

O arquivo enviado não precisa (e não vai) existir no disco do projeto: os
bytes são parseados e o resultado vive apenas no banco, com
origem = 'upload' — o que o mantém fora da limpeza de órfãos e da varredura
em lote. O caminho lógico registrado é "uploads/<pasta_raiz>/<nome>".

Regras de duplicata (na ordem):
  1. mesmo caminho + mesmo hash        → "sem_alteracao" (nada a fazer)
  2. mesmo hash em outro caminho       → "duplicado" (conteúdo idêntico já existe)
  3. mesmo caminho + hash diferente    → reprocessa e substitui ("atualizado")
  4. caso contrário                    → "adicionado"
"""
import hashlib
import logging
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from acervo.core.exceptions import AcervoError, UploadError
from acervo.core.models import Arquivo, Bloco, Categoria
from acervo.ingestion.scanner import EXTENSOES_PARSERS
from acervo.persistence.db import cursor
from acervo.persistence.repository import ArquivoRepository, BlocoRepository, CategoriaRepository
from acervo.search.indexador_service import _PARSERS, _sanitizar_texto

logger = logging.getLogger("acervo.upload")


@dataclass(frozen=True)
class ResultadoUpload:
    status: str  # 'adicionado' | 'atualizado' | 'sem_alteracao' | 'duplicado'
    caminho: str
    total_blocos: int = 0
    duplicado_de: Optional[str] = None


def extensoes_aceitas() -> list[str]:
    """Extensões (sem ponto) que a interface de upload deve aceitar."""
    return sorted(ext.lstrip(".") for ext in EXTENSOES_PARSERS)


def adicionar_conteudo(
    nome_arquivo: str,
    dados: bytes,
    categoria: Categoria,
    *,
    schema: str = "acervo",
    arquivos_repo: Optional[ArquivoRepository] = None,
    blocos_repo: Optional[BlocoRepository] = None,
) -> ResultadoUpload:
    nome_arquivo = Path(nome_arquivo or "").name.strip()
    if not nome_arquivo:
        raise UploadError("Nome de arquivo vazio.")
    if categoria.id is None:
        raise UploadError("Categoria sem id — selecione uma categoria existente.")

    extensao = Path(nome_arquivo).suffix.lower()
    tipo_parser = EXTENSOES_PARSERS.get(extensao)
    if tipo_parser is None:
        aceitas = ", ".join(f".{e}" for e in extensoes_aceitas())
        raise UploadError(f"Extensão '{extensao or '(nenhuma)'}' não suportada. Aceitas: {aceitas}.")

    arquivos_repo = arquivos_repo or ArquivoRepository(schema)
    blocos_repo = blocos_repo or BlocoRepository(schema)

    hash_ = hashlib.sha256(dados).hexdigest()
    caminho = f"uploads/{categoria.pasta_raiz}/{nome_arquivo}"

    try:
        with cursor() as cur:
            hash_existente = arquivos_repo.hash_por_caminho(cur, caminho)
            if hash_existente == hash_:
                return ResultadoUpload(status="sem_alteracao", caminho=caminho)
            caminho_igual = arquivos_repo.caminho_com_hash(cur, hash_)
        if caminho_igual is not None and caminho_igual != caminho:
            return ResultadoUpload(status="duplicado", caminho=caminho, duplicado_de=caminho_igual)
    except AcervoError:
        raise
    except Exception as e:
        raise UploadError(f"Falha ao verificar duplicatas de '{nome_arquivo}': {e}") from e

    blocos_brutos = _parsear_bytes(nome_arquivo, dados, extensao, tipo_parser)

    try:
        with cursor() as cur:
            arquivo_id = arquivos_repo.upsert(cur, Arquivo(
                id=None,
                caminho=caminho,
                categoria_id=categoria.id,
                extensao=extensao,
                tipo="conteudo",
                tamanho_bytes=len(dados),
                hash=hash_,
                duplicado_de=None,
                origem="upload",
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
    except AcervoError as e:
        raise UploadError(f"Falha ao gravar '{nome_arquivo}' no banco: {e}") from e

    status = "atualizado" if hash_existente is not None else "adicionado"
    logger.info("Upload %s: %s (%d bloco(s))", status, caminho, len(blocos_brutos))
    return ResultadoUpload(status=status, caminho=caminho, total_blocos=len(blocos_brutos))


def criar_categoria(
    nome: str,
    subcategoria: Optional[str],
    cor: str,
    *,
    schema: str = "acervo",
    categorias_repo: Optional[CategoriaRepository] = None,
) -> Categoria:
    """Cria (ou reaproveita, se o nome gerar a mesma pasta_raiz) uma categoria."""
    nome = (nome or "").strip()
    if not nome:
        raise UploadError("Informe o nome da categoria.")
    subcategoria = (subcategoria or "").strip() or None
    cor = (cor or "").strip() or "#a78bfa"

    categorias_repo = categorias_repo or CategoriaRepository(schema)
    categoria = Categoria(
        id=None,
        nome=nome,
        subcategoria=subcategoria,
        cor=cor,
        pasta_raiz=_slug_pasta(nome, subcategoria),
    )
    try:
        with cursor() as cur:
            categoria_id = categorias_repo.upsert(cur, categoria)
    except AcervoError as e:
        raise UploadError(f"Falha ao criar a categoria '{nome}': {e}") from e

    return Categoria(
        id=categoria_id,
        nome=nome,
        subcategoria=subcategoria,
        cor=cor,
        pasta_raiz=categoria.pasta_raiz,
    )


def _parsear_bytes(nome_arquivo: str, dados: bytes, extensao: str, tipo_parser: str) -> list:
    """Escreve os bytes num arquivo temporário e delega ao parser da extensão.

    Os parsers trabalham com `Path` (alguns delegam a bibliotecas que exigem
    arquivo real, como pypdf/python-pptx), então o temporário é o contrato
    mais simples que serve a todos.
    """
    parser_fn = _PARSERS[tipo_parser]
    tmp = tempfile.NamedTemporaryFile(suffix=extensao, delete=False)
    try:
        tmp.write(dados)
        tmp.close()
        return parser_fn(Path(tmp.name))
    except AcervoError as e:
        raise UploadError(f"Não foi possível interpretar '{nome_arquivo}': {e}") from e
    except Exception as e:
        raise UploadError(f"Erro inesperado ao interpretar '{nome_arquivo}': {e}") from e
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            logger.warning("Não foi possível remover o temporário '%s'.", tmp.name)


def _slug_pasta(nome: str, subcategoria: Optional[str]) -> str:
    """'Machine Learning', 'Módulo 3' -> 'upload_machine_learning_modulo_3'."""
    base = nome if not subcategoria else f"{nome} {subcategoria}"
    sem_acento = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")
    return f"upload_{slug or 'categoria'}"
