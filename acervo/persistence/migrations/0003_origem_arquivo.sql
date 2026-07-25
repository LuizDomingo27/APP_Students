-- Distingue como cada arquivo entrou no acervo:
--   'varredura' — encontrado no disco pela indexação em lote (scripts/indexar.py)
--   'upload'    — enviado pela interface do app (página "Adicionar")
--
-- A limpeza de órfãos usa isso como salvaguarda: só registros de varredura
-- podem ser removidos quando o arquivo some do disco; uploads vivem apenas
-- no banco e nunca são tocados.

ALTER TABLE "{schema}".arquivos
    ADD COLUMN IF NOT EXISTS origem TEXT NOT NULL DEFAULT 'varredura'
    CHECK (origem IN ('varredura', 'upload'));
