from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class AsyncBaseRepository(Generic[ModelType]):
    """Acceso a datos genérico sobre una sesión asíncrona: cada repositorio concreto solo fija su modelo."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self._session = session
        self._model = model

    async def get(self, entity_id: int) -> ModelType | None:
        return await self._session.get(self._model, entity_id)
