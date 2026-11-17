-- Acesso via login interno, sem credenciais versionadas.
BEGIN;
CREATE TABLE IF NOT EXISTS operacional.usuarios (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  nome TEXT NOT NULL,
  perfil TEXT NOT NULL CHECK (perfil IN ('operador','gestor','administrador')),
  senha_hash TEXT NOT NULL,
  ativo BOOLEAN NOT NULL DEFAULT true,
  criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMIT;
-- Ao usuário de runtime operacional: GRANT SELECT ON operacional.usuarios.
-- Ao papel de provisão (NÃO usado pelo app): GRANT SELECT, INSERT, UPDATE ON operacional.usuarios.
