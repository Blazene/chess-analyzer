-- 0002_sync_state.sql
-- Records that a user's FULL history has been loaded. Incremental syncs are only allowed
-- after that, because "newest stored game" only means "everything older is stored too"
-- once a full load has finished.

CREATE TABLE sync_state (
    lichess_username        TEXT        NOT NULL,
    full_sync_completed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sync_state_pkey PRIMARY KEY (lichess_username),
    CONSTRAINT sync_state_username_not_empty CHECK (lichess_username <> ''),
    CONSTRAINT sync_state_username_lowercase CHECK (lichess_username = lower(lichess_username))
);
