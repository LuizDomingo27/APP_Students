"""Contrato comum que todo parser de arquivo segue."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


@dataclass
class BlocoBruto:
    ordem: int
    titulo: Optional[str]
    explicacao: Optional[str]
    codigo: Optional[str]
    linguagem: Optional[str]


class Parser(Protocol):
    def parse(self, caminho: Path) -> list[BlocoBruto]:
        """Extrai os blocos de conteúdo de um arquivo.

        Deve levantar `ArquivoParseError` (nunca uma exceção crua) quando o
        arquivo não puder ser lido/interpretado.
        """
        ...
