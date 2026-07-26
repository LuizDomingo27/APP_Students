-- Fase 4: área de segurança — o acervo deixa de ser aberto.
--
-- Todo acesso passa a exigir um usuário cadastrado E aprovado por um admin.
-- O cadastro é auto-serviço (qualquer um cria), mas nasce em 'pendente' e não
-- abre nenhuma porta até alguém com papel 'admin' decidir.
--
-- Ciclo de vida do status:
--     pendente  -> aprovado | recusado      (decisão inicial do admin)
--     aprovado <-> bloqueado                (revogar/devolver acesso)
--     recusado  -> aprovado                 (admin muda de ideia)
-- Só 'aprovado' entra no app. Recusar e bloquear NUNCA apagam o registro:
-- manter a linha preserva o histórico da decisão e impede que a mesma pessoa
-- volte para a fila de pendentes só recriando o cadastro com o mesmo e-mail.

CREATE TABLE IF NOT EXISTS "{schema}".usuarios (
    id                SERIAL PRIMARY KEY,
    nome              TEXT NOT NULL,
    -- Sempre gravado em minúsculas pela camada de serviço, para que o UNIQUE
    -- (que é sensível a maiúsculas) de fato impeça "Ana@x.com" e "ana@x.com"
    -- de virarem duas contas distintas.
    email             TEXT NOT NULL UNIQUE,
    senha_hash        TEXT NOT NULL,
    papel             TEXT NOT NULL DEFAULT 'usuario'
                      CHECK (papel IN ('usuario', 'admin')),
    status            TEXT NOT NULL DEFAULT 'pendente'
                      CHECK (status IN ('pendente', 'aprovado', 'recusado', 'bloqueado')),
    -- Ligado quando o admin reseta a senha: o login funciona, mas a interface
    -- obriga a trocar a senha antes de liberar qualquer página.
    senha_temporaria  BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Rastro da última decisão administrativa (quem e quando). Evita uma
    -- tabela de auditoria separada enquanto só interessa o estado corrente.
    decidido_em       TIMESTAMPTZ,
    decidido_por      INT REFERENCES "{schema}".usuarios(id),
    ultimo_acesso     TIMESTAMPTZ
);

-- A fila de pendentes é a consulta que o painel do admin faz a cada carga.
CREATE INDEX IF NOT EXISTS idx_usuarios_status ON "{schema}".usuarios (status);
