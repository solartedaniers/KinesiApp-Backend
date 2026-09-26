# KinesiApp backend

FastAPI + SQLAlchemy + PostgreSQL. Config comes from environment variables (see `.env.example`).
The schema is managed by Alembic — the app never creates tables itself.

## Setup

Startup order matters: the schema must be migrated before the app (or the admin CLI) touches the database.

```bash
pip install -r requirements-dev.txt

# 1. Start Postgres (see docker-compose.yml at the repo root)
docker compose up -d db

# 2. Migrate the schema
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
whatever Postgres `Settings` points to — useful to confirm a fresh/CI database ends up drift-free:

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
