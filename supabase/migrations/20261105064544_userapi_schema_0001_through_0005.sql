-- Faithful replay of integrity-userapi/migrations/*.sql in filename order,
-- plus the schema_migrations rows app/db.py::run_migrations would have written,
-- so the app's own migrator treats these as already applied on startup.
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== 0001_init.sql =====
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash              TEXT NOT NULL UNIQUE,
    ais_trust_ceiling     INTEGER NOT NULL DEFAULT 300,
    revoked_at            TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_api_keys_user_id ON api_keys (user_id);

CREATE TABLE user_agents (
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_did   TEXT NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, agent_did)
);

CREATE TABLE demo_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    result_summary  JSONB
);

CREATE INDEX idx_demo_runs_user_id ON demo_runs (user_id);

-- ===== 0002_jwt_revocation.sql =====
CREATE TABLE revoked_tokens (
    jti         UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    revoked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_revoked_tokens_expires_at ON revoked_tokens (expires_at);

-- ===== 0003_user_wallets.sql =====
CREATE TABLE user_wallets (
    user_id            UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    app_wallet_address TEXT NOT NULL UNIQUE,
    itk_balance_wei    NUMERIC(78,0) NOT NULL DEFAULT 0 CHECK (itk_balance_wei >= 0),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== 0004_policy_packs.sql =====
CREATE TABLE policy_packs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    description         TEXT NOT NULL DEFAULT '',
    agent_did           TEXT,
    mode                TEXT NOT NULL DEFAULT 'observe' CHECK (mode IN ('observe', 'enforce')),
    active_revision     INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_policy_packs_user_id ON policy_packs(user_id);
CREATE INDEX idx_policy_packs_agent_did ON policy_packs(user_id, agent_did);

CREATE TABLE policy_revisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_id         UUID NOT NULL REFERENCES policy_packs(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL CHECK (version > 0),
    rules           JSONB NOT NULL DEFAULT '[]'::jsonb,
    mode            TEXT NOT NULL DEFAULT 'observe' CHECK (mode IN ('observe', 'enforce')),
    change_note     TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(pack_id, version)
);

CREATE INDEX idx_policy_revisions_pack_id ON policy_revisions(pack_id, version DESC);

-- ===== 0005_google_oauth.sql =====
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id TEXT UNIQUE;
ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users (google_id);

-- ===== tracking rows, exactly as run_migrations would insert them =====
INSERT INTO schema_migrations (filename) VALUES
    ('0001_init.sql'),
    ('0002_jwt_revocation.sql'),
    ('0003_user_wallets.sql'),
    ('0004_policy_packs.sql'),
    ('0005_google_oauth.sql');;
