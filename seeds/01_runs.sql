CREATE TABLE IF NOT EXISTS runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    sandbox_name TEXT NOT NULL
        CHECK (sandbox_name ~ '^sbx-[a-z0-9]{8,}$'),
    problem_id TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN (
            'created', 'ready', 'running',
            'succeeded', 'failed', 'deleted'
        )),
    execution_target TEXT NOT NULL
        CHECK (execution_target = 'celesto_sandbox'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO runs (
    run_id,
    sandbox_name,
    problem_id,
    state,
    execution_target
)
VALUES (
    'seed-demo-001',
    'sbx-seeddemo1',
    'demo',
    'deleted',
    'celesto_sandbox'
)
ON CONFLICT (run_id) DO NOTHING;
