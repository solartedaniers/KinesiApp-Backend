# KinesiApp backend

FastAPI + SQLAlchemy + PostgreSQL. Config comes from environment variables (see `.env.example`).

## Setup

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## Admin CLI

Creates the first ADMIN account, or promotes an existing user to ADMIN if the email already exists
(idempotent — safe to run again).

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
