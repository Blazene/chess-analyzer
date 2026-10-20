-- 0003_move_losses.sql
-- One row per move: what it cost the player who made it, under one analysis run.
-- Separate from evaluations because the last position of a checkmate game has no
-- evaluation row, but the checkmating move still needs its (zero) loss recorded.

CREATE TABLE move_losses (
    analysis_run_id  BIGINT  NOT NULL,
    game_id          BIGINT  NOT NULL,
    ply              INTEGER NOT NULL,
    loss_cp          INTEGER NOT NULL,
    label            TEXT    NOT NULL,
    CONSTRAINT move_losses_pkey PRIMARY KEY (analysis_run_id, game_id, ply),
    CONSTRAINT move_losses_analysis_run_id_fkey FOREIGN KEY (analysis_run_id)
        REFERENCES analysis_runs (id) ON DELETE CASCADE,
    CONSTRAINT move_losses_move_fkey FOREIGN KEY (game_id, ply)
        REFERENCES moves (game_id, ply) ON DELETE CASCADE,
    CONSTRAINT move_losses_ply_positive CHECK (ply >= 1),
    CONSTRAINT move_losses_loss_nonnegative CHECK (loss_cp >= 0),
    CONSTRAINT move_losses_label_valid CHECK (
        label IN ('ok', 'inaccuracy', 'mistake', 'blunder')
    )
);

-- Postgres does not index the referencing side of a foreign key by itself.
CREATE INDEX move_losses_game_id_ply_idx ON move_losses (game_id, ply);
