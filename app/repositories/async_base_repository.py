from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class AsyncBaseRepository(Generic[ModelType]):
    """Doy acceso a datos genérico sobre una sesión asíncrona: cada repositorio concreto solo fija su modelo."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self._session = session
        self._model = model

    async def get(self, entity_id: int) -> ModelType | None:
        return await self._session.get(self._model, entity_id)

    def add(self, entity: ModelType) -> None:
        # No hago commit: lo hace la unidad de trabajo, para que un caso de uso confirme todo o nada
        self._session.add(entity)

    async def refresh(self, entity: ModelType) -> None:
        # Traigo lo que pone la base (id, created_at) antes de que la unidad de trabajo suelte la instancia
        await self._session.refresh(entity)
