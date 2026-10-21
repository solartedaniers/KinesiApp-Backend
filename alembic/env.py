from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Importo app.models para que registre todos los modelos en Base.metadata: sin esto, autogenerate
# vería una metadata vacía
import app.models  # noqa: F401
from app.models.base import Base
from app.settings.database import DatabaseSettings

config = context.config

# Saco la URL de DatabaseSettings y no de alembic.ini, para no duplicar credenciales. Solo pido las de
# la base: migrar no debería exigir el secreto JWT ni las credenciales del bucket
config.set_main_option(
    "sqlalchemy.url",
    DatabaseSettings().database_url.render_as_string(hide_password=False).replace("%", "%%"),
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genero el SQL sin conectarme a la base (alembic upgrade --sql)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplico las migraciones con una conexión real, sin pool porque es un proceso de una sola vez."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
