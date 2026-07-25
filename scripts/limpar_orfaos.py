"""Remove do banco os registros de arquivos que sumiram do disco (órfãos).

Seguro por desenho:
  - Pastas raiz que foram removidas por inteiro são PRESERVADAS no banco
    (o conteúdo delas passou a viver só lá).
  - Conteúdos enviados pela interface (origem 'upload') nunca são tocados.
  - Sem --aplicar, apenas simula e mostra o que seria removido.

Uso:
    python scripts/limpar_orfaos.py             # simulação (não remove nada)
    python scripts/limpar_orfaos.py --aplicar   # remove de fato
"""
import argparse
import logging
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from acervo.core.exceptions import AcervoError
from acervo.search.limpeza_service import limpar_orfaos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("acervo.scripts.limpar_orfaos")

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="Limpa registros órfãos do acervo.")
    argparser.add_argument(
        "--aplicar", action="store_true",
        help="Remove de fato (sem esta flag, apenas simula).",
    )
    args = argparser.parse_args()

    try:
        resultado = limpar_orfaos(aplicar=args.aplicar)
    except AcervoError as e:
        logger.error("Limpeza abortada: %s", e)
        raise SystemExit(1) from e

    if resultado.pastas_preservadas:
        print("Pastas ausentes do disco (registros preservados no banco):")
        for pasta in resultado.pastas_preservadas:
            print(f"  - {pasta}")

    if not resultado.orfaos:
        print("Nenhum órfão encontrado.")
    elif resultado.aplicado:
        print(f"{resultado.removidos} registro(s) órfão(s) removido(s):")
        for caminho in resultado.orfaos:
            print(f"  - {caminho}")
    else:
        print(f"{len(resultado.orfaos)} órfão(s) encontrado(s) — simulação, nada foi removido.")
        for caminho in resultado.orfaos:
            print(f"  - {caminho}")
        print("\nPara remover de fato: python scripts/limpar_orfaos.py --aplicar")
