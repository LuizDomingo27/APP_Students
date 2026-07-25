"""Limpeza de órfãos — reconcilia o banco com o disco, com salvaguardas.

Um "órfão" é um registro de arquivo que veio da varredura de disco
(origem = 'varredura') cujo arquivo físico não existe mais DENTRO de uma
pasta raiz que ainda está presente — tipicamente o resultado de um rename
ou de uma reorganização de subpastas.

Duas salvaguardas deliberadas, por causa do fluxo de trabalho do acervo
(o dono apaga pastas inteiras do disco depois que o conteúdo já está no
banco, e o banco vira a fonte da verdade):

  1. Pasta raiz inteira ausente do disco → TODOS os registros dela são
     preservados. Pasta removida significa "conteúdo arquivado no banco",
     nunca "conteúdo a apagar".
  2. Arquivos com origem = 'upload' vivem apenas no banco e jamais entram
     na reconciliação (o filtro é feito no repositório).

Por padrão a execução é uma simulação (dry-run): nada é removido até o
chamador passar `aplicar=True`.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from acervo.ingestion import scanner
from acervo.persistence.db import cursor
from acervo.persistence.repository import ArquivoRepository

logger = logging.getLogger("acervo.limpeza")


@dataclass
class ResultadoLimpeza:
    orfaos: list[str] = field(default_factory=list)
    pastas_preservadas: list[str] = field(default_factory=list)
    removidos: int = 0
    aplicado: bool = False

    def __repr__(self) -> str:
        return (
            f"ResultadoLimpeza(orfaos={len(self.orfaos)}, removidos={self.removidos}, "
            f"pastas_preservadas={self.pastas_preservadas}, aplicado={self.aplicado})"
        )


def limpar_orfaos(
    schema: str = "acervo",
    *,
    raiz: Optional[Path] = None,
    aplicar: bool = False,
    arquivos_repo: Optional[ArquivoRepository] = None,
) -> ResultadoLimpeza:
    arquivos_repo = arquivos_repo or ArquivoRepository(schema)
    raiz = raiz if raiz is not None else scanner.RAIZ
    resultado = ResultadoLimpeza(aplicado=aplicar)

    for pasta_raiz_nome in scanner.carregar_categorias():
        pasta = raiz / pasta_raiz_nome
        if not pasta.is_dir():
            # pasta arquivada: o conteúdo agora vive só no banco — preserva tudo
            resultado.pastas_preservadas.append(pasta_raiz_nome)
            logger.info(
                "Pasta '%s' não existe mais no disco — registros preservados no banco.",
                pasta_raiz_nome,
            )
            continue

        no_disco = {
            str(caminho.relative_to(raiz)).replace("\\", "/")
            for caminho in pasta.rglob("*")
            if caminho.is_file()
        }
        with cursor() as cur:
            no_banco = arquivos_repo.listar_caminhos_de_varredura(cur, pasta_raiz_nome)

        orfaos_da_pasta = sorted(set(no_banco) - no_disco)
        if orfaos_da_pasta:
            logger.info("Pasta '%s': %d órfão(s) encontrado(s).", pasta_raiz_nome, len(orfaos_da_pasta))
        resultado.orfaos.extend(orfaos_da_pasta)

    if aplicar and resultado.orfaos:
        with cursor() as cur:
            resultado.removidos = arquivos_repo.remover_por_caminhos(cur, resultado.orfaos)
        logger.info("Removidos %d registro(s) órfão(s) do banco.", resultado.removidos)

    return resultado
