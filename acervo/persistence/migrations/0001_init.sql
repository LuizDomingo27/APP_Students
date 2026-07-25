-- Schema inicial do Acervo DS.
-- O placeholder {schema} é substituído pelo runner (scripts/aplicar_migrations.py),
-- o que permite rodar o mesmo script tanto no schema de produção ("acervo")
-- quanto em um schema descartável de teste (ex.: "acervo_test_ab12cd34").

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS "{schema}".categorias (
    id            SERIAL PRIMARY KEY,
    nome          TEXT NOT NULL,
    subcategoria  TEXT,
    cor           TEXT NOT NULL,
    pasta_raiz    TEXT NOT NULL,
    UNIQUE (pasta_raiz)
);

CREATE TABLE IF NOT EXISTS "{schema}".arquivos (
    id              SERIAL PRIMARY KEY,
    caminho         TEXT NOT NULL UNIQUE,
    categoria_id    INT NOT NULL REFERENCES "{schema}".categorias(id),
    extensao        TEXT NOT NULL,
    tipo            TEXT NOT NULL CHECK (tipo IN ('conteudo', 'dado', 'outro')),
    tamanho_bytes   BIGINT NOT NULL,
    hash            TEXT NOT NULL,
    duplicado_de    INT REFERENCES "{schema}".arquivos(id),
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_arquivos_hash ON "{schema}".arquivos (hash);
CREATE INDEX IF NOT EXISTS idx_arquivos_categoria ON "{schema}".arquivos (categoria_id);

CREATE TABLE IF NOT EXISTS "{schema}".blocos (
    id            BIGSERIAL PRIMARY KEY,
    arquivo_id    INT NOT NULL REFERENCES "{schema}".arquivos(id) ON DELETE CASCADE,
    ordem         INT NOT NULL,
    titulo        TEXT,
    explicacao    TEXT,
    codigo        TEXT,
    linguagem     TEXT,
    texto_busca   tsvector GENERATED ALWAYS AS (
        to_tsvector('portuguese',
            coalesce(titulo, '') || ' ' || coalesce(explicacao, '') || ' ' || coalesce(codigo, ''))
    ) STORED,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (arquivo_id, ordem)
);
CREATE INDEX IF NOT EXISTS idx_blocos_tsv ON "{schema}".blocos USING GIN (texto_busca);
CREATE INDEX IF NOT EXISTS idx_blocos_codigo_trgm ON "{schema}".blocos USING GIN (codigo gin_trgm_ops);

CREATE TABLE IF NOT EXISTS "{schema}".falhas_indexacao (
    id                SERIAL PRIMARY KEY,
    arquivo_caminho   TEXT NOT NULL,
    etapa             TEXT NOT NULL,
    erro              TEXT NOT NULL,
    ocorrido_em       TIMESTAMPTZ NOT NULL DEFAULT now()
);
