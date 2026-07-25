"""Modelos de domínio do Acervo DS — dataclasses simples, sem I/O.

Representam o que existe no banco (categorias, arquivos, blocos de conteúdo)
e o que a busca devolve, independente de como os dados chegaram lá (Postgres,
arquivo, ou o que vier a substituir isso no futuro).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Categoria:
    id: Optional[int]
    nome: str
    subcategoria: Optional[str]
    cor: str
    pasta_raiz: str


@dataclass(frozen=True)
class Arquivo:
    id: Optional[int]
    caminho: str
    categoria_id: int
    extensao: str
    tipo: str  # 'conteudo' | 'dado' | 'outro'
    tamanho_bytes: int
    hash: str
    duplicado_de: Optional[int]
    origem: str = "varredura"  # 'varredura' | 'upload'


@dataclass(frozen=True)
class Bloco:
    id: Optional[int]
    arquivo_id: int
    ordem: int
    titulo: Optional[str]
    explicacao: Optional[str]
    codigo: Optional[str]
    linguagem: Optional[str]


@dataclass(frozen=True)
class ResultadoBusca:
    bloco_id: int
    arquivo_caminho: str
    categoria_nome: str
    subcategoria: Optional[str]
    titulo: Optional[str]
    explicacao: Optional[str]
    codigo: Optional[str]
    linguagem: Optional[str]
    relevancia: float


@dataclass(frozen=True)
class PaginaBusca:
    """Uma página de resultados + o total geral, para a UI montar a paginação."""
    resultados: tuple[ResultadoBusca, ...]
    total: int
    pagina: int
    limite: int


@dataclass(frozen=True)
class EstatisticaCategoria:
    categoria_nome: str
    subcategoria: Optional[str]
    cor: str
    total_arquivos: int
    total_blocos: int


@dataclass(frozen=True)
class ResumoAcervo:
    total_arquivos: int
    total_blocos: int
    total_falhas: int
    por_categoria: tuple[EstatisticaCategoria, ...]
