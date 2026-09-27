from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Clase base declarativa para todos los modelos ORM."""


def get_db() -> Generator[Session, None, None]:
    # Dependencia de FastAPI: una sesión por request, cerrada siempre al final
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory() -> sessionmaker[Session]:
    # Para trabajo en segundo plano: abre su propia sesión porque la del request
    # ya está cerrada cuando la tarea corre. Los tests la sobrescriben.
    return SessionLocal
