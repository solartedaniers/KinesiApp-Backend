from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.settings.database import DatabaseSettings


def build_async_engine(settings: DatabaseSettings) -> AsyncEngine:
    # En Render la conexión pasa por el pooler de Neon (PgBouncer en modo transacción): apago la caché de
    # sentencias preparadas y les doy nombres únicos para que no choquen entre conexiones del pooler
    url = settings.async_database_url.update_query_dict({"prepared_statement_cache_size": "0"})
    return create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "ssl": settings.POSTGRES_SSL_MODE,
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        },
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # No expiro al hacer commit: en async, leer un atributo expirado dispararía I/O implícito (MissingGreenlet)
    return async_sessionmaker(engine, expire_on_commit=False)
