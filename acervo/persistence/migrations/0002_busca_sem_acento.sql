-- Fase 2: busca insensível a acentos.
--
-- O stemmer 'portuguese' puro diferencia "regressão" de "regressao" — quem
-- digita rápido, sem acento, não encontrava nada. A solução padrão do
-- Postgres é uma text search configuration que passa cada palavra pelo
-- unaccent antes do stemming, aplicada TANTO na coluna indexada quanto na
-- query (o repositório usa a mesma configuração).
--
-- A configuração vive dentro do schema para que os schemas descartáveis de
-- teste tenham a sua própria cópia, criada e derrubada junto com eles.

CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TEXT SEARCH CONFIGURATION "{schema}".portugues_unaccent (COPY = pg_catalog.portuguese);
ALTER TEXT SEARCH CONFIGURATION "{schema}".portugues_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, portuguese_stem;

-- Recria a coluna gerada com a nova configuração (o índice antigo cai junto
-- com a coluna). O Postgres recalcula o tsvector de todas as linhas aqui —
-- reindexação automática, sem precisar reprocessar os arquivos.
ALTER TABLE "{schema}".blocos DROP COLUMN texto_busca;
ALTER TABLE "{schema}".blocos ADD COLUMN texto_busca tsvector GENERATED ALWAYS AS (
    to_tsvector('{schema}.portugues_unaccent'::regconfig,
        coalesce(titulo, '') || ' ' || coalesce(explicacao, '') || ' ' || coalesce(codigo, ''))
) STORED;
CREATE INDEX idx_blocos_tsv ON "{schema}".blocos USING GIN (texto_busca);
