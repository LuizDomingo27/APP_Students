"""Configuração central do Acervo DS.

Lê o `.env` (nunca commitado) e expõe um objeto `Settings` único via
`get_settings()`. Se algo essencial estiver faltando (ex.: DATABASE_URL),
falha imediatamente com uma mensagem clara em vez de deixar o erro
aparecer, obscuro, três camadas depois lá no banco.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from acervo.core.exceptions import ConfiguracaoError

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_CATEGORIAS = RAIZ / "config" / "categorias.json"

load_dotenv(RAIZ / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    log_level: str
    schema: str


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise ConfiguracaoError(
                "DATABASE_URL não definido. Copie .env.example para .env e informe "
                "a connection string do seu projeto Neon (Settings -> Connection Details)."
            )
        _settings = Settings(
            database_url=url,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            schema=os.getenv("DB_SCHEMA", "acervo"),
        )
    return _settings


def resetar_settings_cache() -> None:
    """Usado pelos testes para forçar a releitura do ambiente."""
    global _settings
    _settings = None
