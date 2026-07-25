"""Fase 2 — busca no acervo direto do terminal.

Uso:
    python scripts/buscar.py "regressão linear"
    python scripts/buscar.py "df.groupby" --modo codigo
    python scripts/buscar.py "window function" --categoria "Scripts SQL" --limite 5
"""
import argparse
import sys
from pathlib import Path

# o console do Windows usa cp1252 por padrão e não representa todo o
# conteúdo do acervo (acentos combinantes, símbolos) — força UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from acervo.core.exceptions import BuscaError
from acervo.search.busca_service import MODOS_VALIDOS, buscar, opcoes_de_filtro


def _resolver_categoria_id(nome: str) -> int:
    categorias = opcoes_de_filtro()["categorias"]
    for c in categorias:
        if c.nome.lower() == nome.lower():
            return c.id
    disponiveis = ", ".join(sorted({c.nome for c in categorias}))
    raise BuscaError(f"Categoria '{nome}' não existe. Disponíveis: {disponiveis}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Busca no Acervo DS (Neon)")
    parser.add_argument("termo", help="termo de busca")
    parser.add_argument("--modo", choices=MODOS_VALIDOS, default="texto")
    parser.add_argument("--categoria", help="filtra pelo nome da categoria (ex.: 'Data Science')")
    parser.add_argument("--linguagem", help="filtra pela linguagem do bloco (ex.: python, sql)")
    parser.add_argument("--pagina", type=int, default=1)
    parser.add_argument("--limite", type=int, default=10)
    args = parser.parse_args()

    try:
        categoria_id = _resolver_categoria_id(args.categoria) if args.categoria else None
        resultado = buscar(
            args.termo,
            modo=args.modo,
            categoria_id=categoria_id,
            linguagem=args.linguagem,
            pagina=args.pagina,
            limite=args.limite,
        )
    except BuscaError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1

    if resultado.total == 0:
        print("Nenhum resultado.")
        return 0

    print(f"{resultado.total} resultado(s) — página {resultado.pagina} "
          f"(mostrando {len(resultado.resultados)})\n")
    for r in resultado.resultados:
        cabecalho = f"[{r.categoria_nome}] {r.arquivo_caminho}"
        print(cabecalho)
        if r.titulo:
            print(f"  Título: {r.titulo}")
        if r.explicacao:
            resumo = r.explicacao.replace("\n", " ")
            print(f"  {resumo[:200]}{'…' if len(resumo) > 200 else ''}")
        if r.codigo:
            primeira_linha = next((ln for ln in r.codigo.splitlines() if ln.strip()), "")
            print(f"  Código ({r.linguagem or '?'}): {primeira_linha[:120]}")
        print(f"  relevância: {r.relevancia:.4f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
