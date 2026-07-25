"""Fase 1 — roda a extração de conteúdo de todas as pastas e grava no Neon.

Uso:
    python scripts/indexar.py
"""
import logging
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from acervo.core.exceptions import AcervoError
from acervo.search.indexador_service import indexar_tudo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("acervo.scripts.indexar")

if __name__ == "__main__":
    try:
        resultado = indexar_tudo()
    except AcervoError as e:
        logger.error("Indexação abortada: %s", e)
        raise SystemExit(1) from e

    print(resultado)
