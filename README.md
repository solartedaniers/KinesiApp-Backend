# KinesiApp backend

FastAPI + SQLAlchemy + PostgreSQL. Config comes from environment variables (see `.env.example`).
The schema is managed by Alembic — the app never creates tables itself.

## Setup

Startup order matters: the schema must be migrated before the app (or the admin CLI) touches the database.

```bash
pip install -r requirements-dev.txt

# 0. Download the pose model (the Docker image does this at build time, pinned by checksum)
curl -L -o models/pose_landmarker_full.task   https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task

# 1. Point the root .env at Neon (no local Postgres anymore): POSTGRES_HOST/PORT/USER/PASSWORD/DB
#    from Neon's DIRECT connection string (host without "-pooler"), see .env.example.
#    libpq reads PGSSLMODE from the process environment, not from .env:
export PGSSLMODE=require          # PowerShell: $env:PGSSLMODE="require"

# 2. Migrate the schema (this runs against Neon: it is the real database)
alembic upgrade head

# 3. Create the first admin
python -m app.cli create-admin

# 4. Run the API
uvicorn app.main:app --reload
```

If you already have a dev database created the old way (via `Base.metadata.create_all`, before
Alembic existed here) and its schema matches the current models, don't run the baseline migration
against it — it would try to create tables that already exist. Instead, mark it as already migrated:

```bash
alembic stamp head
```

`alembic check` (see below) will tell you if that database's schema actually matches the models
before you trust the stamp.

## Migrations

The connection URL always comes from `Settings` (`app/core/config.py`), never from `alembic.ini`.

```bash
# generate a new migration after changing a model
alembic revision --autogenerate -m "add some_column to users"

# review the generated file by hand before committing — autogenerate
# does not always get Postgres Enum names, indexes or FKs right

# apply pending migrations
alembic upgrade head

# check the current DB against the models with no side effects
alembic check
```

`scripts/check_migrations.py` runs `alembic upgrade head` + `alembic check` in one shot against
whatever Postgres `Settings` points to — with the .env on Neon that means it **applies pending
migrations to Neon**. Useful to confirm a fresh/CI database (e.g. a Neon branch) ends up drift-free:

```bash
python scripts/check_migrations.py
```

## Admin CLI

Creates the first ADMIN account, or promotes an existing user to ADMIN if the email already exists
(idempotent — safe to run again). Fails with a clear error instead of creating tables if the schema
hasn't been migrated yet (`alembic upgrade head` first).

```bash
python -m app.cli create-admin
```

Credentials are read from `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_FULL_NAME` env vars. Any missing
one is prompted interactively (the password via `getpass`, so it's never echoed or logged). Credentials
never live in the repo.

## Tests

```bash
pytest
```

Tests never touch Neon: they run on in-memory SQLite, and `tests/conftest.py` sets dummy
`POSTGRES_*` env vars that take precedence over the `.env`.

`tests/test_analysis_real_videos.py` runs MediaPipe on the spike videos
(`spikes/pose_spike/videos/`, not versioned) and is skipped when they or the model are missing.
Every other test runs without MediaPipe: the API tests swap the analyzer for a stub
(`tests/conftest.py`).
