"""Corre 'alembic upgrade head' y 'alembic check' contra la Postgres real
configurada en Settings, para confirmar que las migraciones aplican limpio y
que no quedó drift entre los modelos y la última migración.

No usa SQLite: apunta a la misma base que usaría la app (ver app/core/config.py),
así que antes hay que levantar Postgres (ver README.md).

Uso: python scripts/check_migrations.py
"""
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run(*args: str) -> int:
    print(f"$ alembic {' '.join(args)}")
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR)
    return result.returncode


def main() -> None:
    if _run("upgrade", "head") != 0:
        sys.exit("alembic upgrade head falló.")
    if _run("check") != 0:
        sys.exit("alembic check detectó diferencias entre los modelos y las migraciones.")
    print("OK: esquema migrado y sin drift respecto a los modelos.")


if __name__ == "__main__":
    main()
