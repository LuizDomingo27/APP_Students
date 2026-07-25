"""Varre as pastas de conteúdo configuradas em config/categorias.json e
descreve cada arquivo encontrado (sem ler/parsear o conteúdo ainda).

Falha ao ler um arquivo individual (permissão negada, link quebrado) é
logada e o arquivo é pulado — nunca derruba a varredura inteira.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from acervo.core.exceptions import ConfiguracaoError

logger = logging.getLogger("acervo.scanner")

RAIZ = Path(__file__).resolve().parent.parent.parent
CONFIG_CATEGORIAS = RAIZ / "config" / "categorias.json"

# pastas do próprio projeto — nunca fazem parte do conteúdo a indexar
PASTAS_IGNORADAS = {"app", "scripts", "data", "config", "acervo", "tests", ".claude", ".git", ".venv"}

# extensão -> parser responsável (definido em acervo.ingestion.parsers)
EXTENSOES_PARSERS = {
    ".ipynb": "notebook",
    ".sql": "sql",
    ".txt": "texto",
    ".md": "texto",
    ".py": "texto",
    ".js": "texto",
    ".pdf": "pdf",
    ".pptx": "pptx",
}


@dataclass(frozen=True)
class ArquivoBruto:
    caminho_absoluto: Path
    caminho_relativo: str
    pasta_raiz: str
    extensao: str
    tipo_parser: Optional[str]
    tamanho_bytes: int
    hash: str


def carregar_categorias() -> dict:
    try:
        with open(CONFIG_CATEGORIAS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfiguracaoError(f"Não foi possível carregar '{CONFIG_CATEGORIAS}': {e}") from e


def calcular_hash(caminho: Path, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while chunk := f.read(bloco):
            h.update(chunk)
    return h.hexdigest()


def listar_arquivos(raiz: Path = RAIZ) -> Iterator[ArquivoBruto]:
    categorias = carregar_categorias()

    for pasta_raiz_nome in categorias:
        pasta_raiz = raiz / pasta_raiz_nome
        if not pasta_raiz.is_dir():
            logger.warning("Pasta configurada não encontrada: %s", pasta_raiz_nome)
            continue

        for caminho in pasta_raiz.rglob("*"):
            if not caminho.is_file():
                continue
            if any(parte in PASTAS_IGNORADAS for parte in caminho.parts):
                continue

            try:
                tamanho = caminho.stat().st_size
                digest = calcular_hash(caminho)
            except OSError as e:
                logger.warning("Não foi possível ler '%s': %s", caminho, e)
                continue

            ext = caminho.suffix.lower()
            yield ArquivoBruto(
                caminho_absoluto=caminho,
                caminho_relativo=str(caminho.relative_to(raiz)).replace("\\", "/"),
                pasta_raiz=pasta_raiz_nome,
                extensao=ext,
                tipo_parser=EXTENSOES_PARSERS.get(ext),
                tamanho_bytes=tamanho,
                hash=digest,
            )
