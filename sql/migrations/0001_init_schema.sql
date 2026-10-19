-- 0001_init_schema.sql
-- Core tables: games, moves, analysis_runs, evaluations.
--
-- Conventions used throughout:
--   * Evaluations are stored from WHITE's point of view, in integer centipawns.
--     Positive means White is better, negative means Black is better.
--   * Clocks are integer centiseconds (no floats, same idea as money in paise).
--   * ply 1 is White's first move, ply 2 is Black's first move, and so on.
--     Ply 0 means the starting position, before any move.

CREATE TABLE games (
    id                BIGINT GENERATED ALWAYS AS IDENTITY,
    lichess_id        TEXT        NOT NULL,
    played_at         TIMESTAMPTZ NOT NULL,
    speed             TEXT        NOT NULL,
    rated             BOOLEAN     NOT NULL,
    color             TEXT        NOT NULL,
    result            TEXT        NOT NULL,
    status            TEXT        NOT NULL,
    rating            INTEGER,
    rating_diff       INTEGER,
    opponent_name     TEXT        NOT NULL,
    opponent_rating   INTEGER,
    opponent_is_ai    BOOLEAN     NOT NULL DEFAULT FALSE,
    opening_eco       TEXT,
    opening_name      TEXT,
    opening_ply       INTEGER,
    clock_initial     INTEGER,
    clock_increment   INTEGER,
    moves_san         TEXT        NOT NULL,
    lichess_analysis  JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT games_pkey PRIMARY KEY (id),
    CONSTRAINT games_lichess_id_unique UNIQUE (lichess_id),
    CONSTRAINT games_lichess_id_format CHECK (lichess_id ~ '^[A-Za-z0-9]{8}$'),
    CONSTRAINT games_speed_valid CHECK (
        speed IN ('ultraBullet', 'bullet', 'blitz', 'rapid', 'classical', 'correspondence')
    ),
    CONSTRAINT games_color_valid CHECK (color IN ('white', 'black')),
    CONSTRAINT games_result_valid CHECK (result IN ('win', 'loss', 'draw')),
    CONSTRAINT games_status_not_empty CHECK (status <> ''),
    CONSTRAINT games_rating_positive CHECK (rating IS NULL OR rating > 0),
    CONSTRAINT games_opponent_rating_positive CHECK (
        opponent_rating IS NULL OR opponent_rating > 0
    ),
    CONSTRAINT games_opening_eco_format CHECK (
        opening_eco IS NULL OR opening_eco ~ '^[A-E][0-9]{2}$'
    ),
    CONSTRAINT games_opening_ply_nonnegative CHECK (opening_ply IS NULL OR opening_ply >= 0),
    CONSTRAINT games_clock_initial_nonnegative CHECK (
        clock_initial IS NULL OR clock_initial >= 0
    ),
    CONSTRAINT games_clock_increment_nonnegative CHECK (
        clock_increment IS NULL OR clock_increment >= 0
    ),
    CONSTRAINT games_lichess_analysis_array CHECK (
        lichess_analysis IS NULL OR jsonb_typeof(lichess_analysis) = 'array'
    )
);

CREATE INDEX games_played_at_idx ON games (played_at DESC);

CREATE TABLE moves (
    game_id    BIGINT  NOT NULL,
    ply        INTEGER NOT NULL,
    san        TEXT    NOT NULL,
    uci        TEXT    NOT NULL,
    fen_after  TEXT    NOT NULL,
    clock_cs   INTEGER,
    CONSTRAINT moves_pkey PRIMARY KEY (game_id, ply),
    CONSTRAINT moves_game_id_fkey FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE,
    CONSTRAINT moves_ply_positive CHECK (ply >= 1),
    CONSTRAINT moves_clock_nonnegative CHECK (clock_cs IS NULL OR clock_cs >= 0)
);

-- One row per analysis SETTING (engine + depth), not per execution.
CREATE TABLE analysis_runs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY,
    engine_name TEXT        NOT NULL,
    depth       INTEGER     NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT analysis_runs_pkey PRIMARY KEY (id),
    CONSTRAINT analysis_runs_settings_unique UNIQUE (engine_name, depth),
    CONSTRAINT analysis_runs_engine_not_empty CHECK (engine_name <> ''),
    CONSTRAINT analysis_runs_depth_positive CHECK (depth > 0)
);

-- Engine verdict on the position AFTER ply N (ply 0 = starting position).
-- Exactly one of stockfish_cp / stockfish_mate is set.
--   stockfish_mate > 0: White mates in that many moves. < 0: Black mates.
CREATE TABLE evaluations (
    analysis_run_id  BIGINT  NOT NULL,
    game_id          BIGINT  NOT NULL,
    ply              INTEGER NOT NULL,
    stockfish_cp     INTEGER,
    stockfish_mate   INTEGER,
    best_move        TEXT,
    CONSTRAINT evaluations_pkey PRIMARY KEY (analysis_run_id, game_id, ply),
    CONSTRAINT evaluations_analysis_run_id_fkey FOREIGN KEY (analysis_run_id)
        REFERENCES analysis_runs (id) ON DELETE CASCADE,
    CONSTRAINT evaluations_game_id_fkey FOREIGN KEY (game_id)
        REFERENCES games (id) ON DELETE CASCADE,
    CONSTRAINT evaluations_ply_nonnegative CHECK (ply >= 0),
    CONSTRAINT evaluations_cp_xor_mate CHECK ((stockfish_cp IS NULL) <> (stockfish_mate IS NULL))
);

CREATE INDEX evaluations_game_id_idx ON evaluations (game_id);
