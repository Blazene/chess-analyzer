# Chess Analyzer

![CI](https://github.com/Blazene/chess-analyzer/actions/workflows/ci.yml/badge.svg)

**Live demo:** https://chess-analyzer-hk7he9r4rlz4lebdrmgtf3.streamlit.app (free hosting: after a quiet period the first load can take several seconds while the app and database wake up)

Downloads my Lichess games, analyzes every move with Stockfish, stores the results in PostgreSQL, and shows where I lose points (openings, game phase, time pressure) in a Streamlit dashboard.

![Overview tab](docs/images/overview.png)

## What it does

1. **Fetch.** Streams my games from the Lichess API and stores them, with every move replayed into one row per ply (SAN, UCI, board position, clock). Re-running changes nothing.
2. **Analyze.** Runs Stockfish at depth 14 over every position, several games in parallel.
3. **Score.** Works out how many centipawns each move cost the player who made it, and labels it ok, inaccuracy, mistake or blunder.
4. **Show.** A dashboard filtered by colour, time control and date range: opening results, accuracy by game phase, blunders by time left on the clock, and trends by month.

## The data

Fetched 2,010 games. 1,960 are stored and 50 are skipped (33 from a custom position, 11 Chess960, 6 aborted). The 1,960 stored games hold 115,382 moves and run from October 2022 to October 2026. About 20% of them carry Lichess's own analysis, which I use for a cross-check below.

## Results

Analyzed 1960 games, completed 116910 position evaluations at depth 14 with Stockfish

### Cross-check against Lichess

For the games that have Lichess's own evaluations, `compare.py` checks that every game has one loss row per move and compares our evaluations with theirs. The two will not match exactly, because Lichess's search depth differs from mine.

Positions compared: 19,761
Mean absolute difference: 63 cp (both capped at 1000)
Same side ahead when both show 50+ cp: 100.0% of 12,807

### What my own games show

- For 3+0 Rapid games, my blunder rate is highest when my time is below 10 seconds, at 7.53% blunders, as compared to 5.39% when my time is above 30 seconds.
- Across Rapid and Blitz, my middlegames have the highest amount of blunders, at 6.03% and 6.75% respectively, as compared to 5.10% and 5.95% in the opening and 4.16% and 5.65% in the endgame.

![Openings tab](docs/images/openings.png)
![Clock tab](docs/images/clock.png)
![Trend tab](docs/images/trend.png)

The gap in the trend chart is real: I played no games between late July and early October 2026, and the chart leaves those months empty instead of drawing a line across them.

## Run it yourself

Needs Python 3.11 or newer (uv installs it), [uv](https://docs.astral.sh/uv/), Docker, and Stockfish (only for analysis, not for the dashboard).

```
git clone https://github.com/Blazene/chess-analyzer.git
cd chess-analyzer
cp .env.example .env          # then put your Lichess username in .env
brew install stockfish        # macOS; use your package manager elsewhere
uv sync
docker compose up -d          # PostgreSQL on port 5433
```

Create the tables:

```
PYTHONPATH=src uv run python -c "from config import DATABASE_URL; from migrate import apply_migrations; print(apply_migrations(DATABASE_URL))"
```

Load, analyze, check, view:

```
uv run python src/sync.py                # load your games (add --full for the complete history)
uv run python src/batch.py --workers 6   # analyze them; safe to stop and restart
uv run python src/compare.py             # consistency check and Lichess comparison
uv run streamlit run src/dashboard.py    # open http://localhost:8501
```

`.env` needs three settings, listed in `.env.example`: `LICHESS_USERNAME`, `DATABASE_URL` and `STOCKFISH_PATH`.

### Dashboard in Docker

The image holds only the dashboard. It reads saved results and has no Stockfish.

```
docker build -t chess-analyzer .
docker run --rm -p 8501:8501 -e DATABASE_URL=postgresql://analyzer:analyzer@host.docker.internal:5433/chess_analyzer -e LICHESS_USERNAME=your_lichess_username -e STOCKFISH_PATH=/unused chess-analyzer
```

The dashboard only uses `DATABASE_URL`, but `config.py` insists on all three settings, so the other two get dummy values. That is a known wart.


## Deployment

The dashboard runs on Streamlit Community Cloud and reads from a free managed PostgreSQL database on Neon. The analysis still runs on my machine, because the cloud side only serves saved results.

- **Analysis stays local.** Stockfish and the batch run use my local PostgreSQL. A dump of that database was restored into Neon.
- **Read-only access.** The app connects with a database role that can only read, so a leaked credential could not change any data.
- **No secrets in Git.** The connection string lives in the host's secrets settings. Tests check that `.env` and Streamlit's secrets file are git-ignored, and that no tracked file contains a Neon hostname.
- **Docker is a second option.** The `Dockerfile` runs the same dashboard anywhere and CI builds it on every push, but the live site does not use it.

The live data is a snapshot of my local database. There is no automatic sync: showing newly analyzed games means reloading the data into Neon by hand. On free tiers the app and database sleep when idle, so a first visit after a quiet period is slower.

## How it works

Evaluations are stored in integer centipawns from White's point of view, with a mate score in its own column. Exactly one of the two is set, and a database constraint enforces it. One function decides the sign convention, and tests cover both colours.

A move's loss is measured from the mover's point of view and never goes below zero. Scores are capped at 1,000 centipawns and any mate counts as the cap, so mate in 3 and mate in 9 look the same. A move that delivers checkmate has zero loss. The final position of a checkmate game has no evaluation.

Labels come from how much win probability a move gave away, using a logistic curve on the capped score. The thresholds are 5, 10 and 15 win-percentage points, and they are my own choice, not Lichess's. A move losing 200 centipawns from a won position is not treated like one losing 200 from an equal position.

Each game is stored and analyzed in its own transaction, so a stopped run loses at most the games in progress, and a game is either fully saved or not at all. Games already analyzed are skipped on the next run.

Filters (colour, time control, dates, games against the computer) are applied in SQL before anything is averaged, because an average cannot be re-filtered afterwards. There is no ORM: the SQL is written by hand and lives in `db.py`, `insights.py` and `time_insights.py`.

### Speed

Depth 14 takes about 0.077 seconds per position on one process (1,211 positions in 94 seconds). Depth was chosen on one game: depths 14 and 18 listed the same three biggest drops, while depth 10 added a false one and missed a real one. Parallel speed-up on my M5 MacBook Air (4 performance and 6 efficiency cores), measured on the 12 newest games (about 625 positions) at depth 14:

| Workers | Time   | Speed-up |
| ------- | ------ | -------- |
| 1       | 45.4 s | 1.0x     |
| 2       | 26.0 s | 1.7x     |
| 4       | 16.8 s | 2.7x     |
| 6       | 14.3 s | 3.2x     |
| 8       | 12.5 s | 3.6x     |

### Query performance

The seven dashboard queries were measured with `EXPLAIN ANALYZE`. Three candidate indexes were each tried inside a rolled-back transaction. The planner used none of them and none helped, so none was added. The whole dashboard loads in about 312 ms on 1,960 games. The slowest query is phase accuracy, at a median of 226 ms.

## Tests and CI

The suite has over 400 tests (`uv run pytest -q`).

- **Schema:** constraint tests assert which exact constraint fired, not just that something failed.
- **Database:** each test runs inside a transaction that is rolled back, against a test database rebuilt from the real migration files.
- **Lichess:** the HTTP layer is replaced by a fake, so tests need no network and cannot hit rate limits.
- **Engine:** the game-walking logic runs against a fake engine, and a smaller group runs real Stockfish on forced-mate positions for both colours. Those skip locally if Stockfish is missing.
- **Dashboard:** the data layer is tested against the database, and the page runs inside Streamlit's `AppTest`.

The tests need a second database. Create it once:

```
docker exec chess_analyzer_db psql -U analyzer -d chess_analyzer -c "CREATE DATABASE chess_analyzer_test"
```

I also break the code on purpose after each piece and check that a test fails (by hand, not automated).

GitHub Actions runs on every push, on Ubuntu with a PostgreSQL 16 service and Stockfish from the Ubuntu package. It checks Ruff, formatting and the tests, and fails the build if any test was skipped, so the real-engine tests cannot silently drop out. A second job builds the dashboard image and checks that the container starts and reports healthy. The CI Stockfish is version 16. The analyses on my machine used version 19.

## Limitations

- **One Lichess account.** The games table has no user column, so pointing the tool at another account would mix the data.
- **50 games are not stored** (the skipped variants and aborted games). Games that fail to load are printed, not saved.
- **Stored games are never updated.** Lichess analysis added to a game later is not picked up.
- **Incremental sync can miss a game** that started more than 30 days before it finished. `--full` is the catch-all.
- **The rate-limit retry** (HTTP 429) has only been tested against a fake, never seen live.
- **Depth 14 is a trade-off.** Its evaluations can differ from depth 18 by up to about 20%, so a move near a label threshold may land in the neighbouring label.
- **The thresholds and the game-phase rule are my own.** The opening is the first 10 moves by each side. The endgame is 6 or fewer minor and major pieces on the board. This ignores pawn structure. The curve constant behind the win probability is one I recall from Lichess's code and have not verified.
- **The dashboard caches for 5 minutes.** The sidebar has a button to reload.
- **Results depend on the engine.** An analysis run is identified by engine name and depth, so a different Stockfish version creates a separate run.
- **The live site is a snapshot.** New games appear there only after I reload the data into Neon by hand.

## Project layout

| File                | What it does                                                                |
| ------------------- | --------------------------------------------------------------------------- |
| `config.py`         | Reads settings from `.env` and stops with a clear message if any is missing |
| `models.py`         | The `Game` dataclass and the only parser of Lichess's JSON                  |
| `fetch.py`          | Lichess client (retry on rate limits) and a preview command                 |
| `migrate.py`        | Applies `sql/migrations/*.sql` in order                                     |
| `replay.py`         | Replays the moves into one row per ply                                      |
| `db.py`             | Writes games, moves and analysis; each game in one transaction              |
| `sync.py`           | Loads games into PostgreSQL, with an incremental mode                       |
| `engine.py`         | Stockfish wrapper and the single sign convention                            |
| `analyze.py`        | Walks one game through Stockfish and prints its evaluation curve            |
| `loss.py`           | Centipawn loss, capped mates and move labels (pure functions)               |
| `batch.py`          | Analyzes all games, resumable, with a process pool                          |
| `bench.py`          | Times different worker counts without saving anything                       |
| `compare.py`        | Consistency check and comparison with Lichess's evaluations                 |
| `filters.py`        | The one definition of which games and moves count                           |
| `insights.py`       | Opening results and accuracy by game phase                                  |
| `time_insights.py`  | Results and accuracy by time control, clock and month                       |
| `dashboard_data.py` | Loads everything the dashboard shows and shapes the tables                  |
| `charts.py`         | Plotly figures built from those tables                                      |
| `dashboard.py`      | The Streamlit page                                                          |
| `explain.py`        | `EXPLAIN ANALYZE` tool with rolled-back index trials                        |
| `check.py`          | Quick health check that Stockfish and PostgreSQL respond                    |

Migrations in `sql/migrations/`:

| Migration              | Contents                                 |
| ---------------------- | ---------------------------------------- |
| `0001_init_schema.sql` | games, moves, analysis_runs, evaluations |
| `0002_sync_state.sql`  | marker that the full history was loaded  |
| `0003_move_losses.sql` | one loss and label per move              |
