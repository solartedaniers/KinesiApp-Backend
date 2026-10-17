from app.core.async_database import build_async_engine
from app.settings.database import DatabaseSettings


def test_async_engine_disables_prepared_statement_caches_for_the_neon_pooler() -> None:
    settings = DatabaseSettings(
        _env_file=None,
        POSTGRES_USER="user",
        POSTGRES_PASSWORD="p@ss:word",
        POSTGRES_HOST="ep-test-pooler.neon.tech",
        POSTGRES_DB="kinesiapp",
    )

    engine = build_async_engine(settings)

    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.password == "p@ss:word"
    _, connect_options = engine.dialect.create_connect_args(engine.url)
    assert int(connect_options["prepared_statement_cache_size"]) == 0
