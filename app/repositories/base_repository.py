from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Acceso a datos genérico: cada repositorio concreto solo fija su modelo."""

    def __init__(self, db: Session, model: type[ModelType]) -> None:
        self._db = db
        self._model = model

    def get(self, entity_id: int) -> ModelType | None:
        return self._db.get(self._model, entity_id)

    def list(self, skip: int = 0, limit: int = 100) -> list[ModelType]:
        return list(self._db.query(self._model).offset(skip).limit(limit).all())

    def add(self, entity: ModelType) -> ModelType:
        self._db.add(entity)
        self._db.commit()
        self._db.refresh(entity)
        return entity
