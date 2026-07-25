"""
Fase 0 - Gera o inventario de arquivos das 8 pastas de conteudo e detecta
duplicatas (arquivos e pastas inteiras repetidas), sem apagar ou mover nada.

Saidas (em data/):
  inventario.csv         -> lista de todos os arquivos indexaveis com metadados
  duplicatas_arquivos.json -> grupos de arquivos com conteudo identico (mesmo hash)
  duplicatas_pastas.json   -> pastas cujo conjunto de arquivos e identico a outra pasta
"""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_CATEGORIAS = RAIZ / "config" / "categorias.json"
SAIDA_DIR = RAIZ / "data"

# pastas do proprio projeto, nunca fazem parte do conteudo a indexar
PASTAS_IGNORADAS = {"app", "scripts", "data", "config", ".claude", ".git"}

# extensoes cujo conteudo textual sera extraido nas fases seguintes
EXTENSOES_CONTEUDO = {
    ".ipynb", ".sql", ".py", ".txt", ".md", ".pdf", ".pptx", ".js",
}
# extensoes de dados/binarios: so registradas no inventario, nao indexadas como texto
EXTENSOES_DADOS = {
    ".csv", ".xlsx", ".xls", ".parquet", ".json", ".png", ".jpg", ".jpeg",
    ".zip", ".rar", ".dbc", ".brm3", ".mwb", ".drawio", ".data",
}


def carregar_categorias() -> dict:
    with open(CONFIG_CATEGORIAS, encoding="utf-8") as f:
        return json.load(f)


def calcular_hash(caminho: Path, bloco=1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while chunk := f.read(bloco):
            h.update(chunk)
    return h.hexdigest()


def classificar_arquivo(ext: str) -> str:
    if ext in EXTENSOES_CONTEUDO:
        return "conteudo"
    if ext in EXTENSOES_DADOS:
        return "dado"
    return "outro"


def gerar_inventario():
    categorias = carregar_categorias()
    linhas = []
    hash_por_arquivo = {}  # hash -> lista de caminhos relativos
    hash_por_pasta = defaultdict(list)  # hash_conjunto_da_pasta -> lista de pastas

    for pasta_raiz_nome, meta in categorias.items():
        pasta_raiz = RAIZ / pasta_raiz_nome
        if not pasta_raiz.is_dir():
            print(f"[aviso] pasta configurada nao encontrada: {pasta_raiz_nome}")
            continue

        hashes_por_subpasta = defaultdict(list)

        for caminho in pasta_raiz.rglob("*"):
            if not caminho.is_file():
                continue
            if any(parte in PASTAS_IGNORADAS for parte in caminho.parts):
                continue

            try:
                tamanho = caminho.stat().st_size
                digest = calcular_hash(caminho)
            except (OSError, PermissionError) as e:
                print(f"[erro] nao foi possivel ler {caminho}: {e}")
                continue

            relativo = caminho.relative_to(RAIZ)
            ext = caminho.suffix.lower()
            subpasta = str(caminho.parent.relative_to(pasta_raiz)) if caminho.parent != pasta_raiz else ""

            linhas.append({
                "caminho": str(relativo).replace("\\", "/"),
                "pasta_raiz": pasta_raiz_nome,
                "categoria": meta["categoria"],
                "subcategoria": meta.get("subcategoria") or "",
                "subpasta": subpasta,
                "arquivo": caminho.name,
                "extensao": ext,
                "tipo": classificar_arquivo(ext),
                "tamanho_bytes": tamanho,
                "hash": digest,
            })

            hash_por_arquivo.setdefault(digest, []).append(str(relativo).replace("\\", "/"))
            hashes_por_subpasta[caminho.parent].append(digest)

        # assinatura de cada subpasta = hash ordenado do conjunto de arquivos que ela contem
        for subpasta, hashes in hashes_por_subpasta.items():
            assinatura = hashlib.sha256("".join(sorted(hashes)).encode()).hexdigest()
            hash_por_pasta[assinatura].append(str(subpasta.relative_to(RAIZ)).replace("\\", "/"))

    SAIDA_DIR.mkdir(exist_ok=True)

    # inventario.csv
    campos = ["caminho", "pasta_raiz", "categoria", "subcategoria", "subpasta",
              "arquivo", "extensao", "tipo", "tamanho_bytes", "hash"]
    with open(SAIDA_DIR / "inventario.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)

    # duplicatas de arquivos (mesmo conteudo, caminhos diferentes)
    duplicatas_arquivos = {h: caminhos for h, caminhos in hash_por_arquivo.items() if len(caminhos) > 1}
    with open(SAIDA_DIR / "duplicatas_arquivos.json", "w", encoding="utf-8") as f:
        json.dump(duplicatas_arquivos, f, ensure_ascii=False, indent=2)

    # duplicatas de pastas inteiras (mesmo conjunto de arquivos)
    duplicatas_pastas = {h: pastas for h, pastas in hash_por_pasta.items() if len(pastas) > 1}
    with open(SAIDA_DIR / "duplicatas_pastas.json", "w", encoding="utf-8") as f:
        json.dump(duplicatas_pastas, f, ensure_ascii=False, indent=2)

    total_arquivos_duplicados = sum(len(v) - 1 for v in duplicatas_arquivos.values())
    total_pastas_duplicadas = sum(len(v) - 1 for v in duplicatas_pastas.values())

    print(f"Inventario gerado: {len(linhas)} arquivos -> data/inventario.csv")
    print(f"Grupos de arquivos duplicados: {len(duplicatas_arquivos)} "
          f"({total_arquivos_duplicados} copias redundantes) -> data/duplicatas_arquivos.json")
    print(f"Grupos de pastas duplicadas: {len(duplicatas_pastas)} "
          f"({total_pastas_duplicadas} pastas redundantes) -> data/duplicatas_pastas.json")


if __name__ == "__main__":
    gerar_inventario()
