from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason
from sqlalchemy.exc import IntegrityError

from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.team import Team
from app.models.user import UserRole
from app.repositories.unit_of_work import UnitOfWork
from app.storage.avatar_files import AvatarFiles


class TeamCatalog:
    """Creo, muestro, renombro y borro equipos: el coach maneja los suyos y el admin los de cualquiera."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], logo_files: AvatarFiles) -> None:
        self._uow_factory = uow_factory
        self._logo_files = logo_files

    async def list(self, principal: Principal) -> list[Team]:
        async with self._uow_factory() as uow:
            if principal.role == UserRole.ADMIN:
                return await uow.teams.list_all()
            return await uow.teams.list_by_owner(principal.user_id)

    async def create(self, principal: Principal, name: str) -> Team:
        async with self._uow_factory() as uow:
            await _require_free_name(uow, principal.user_id, name)
            team = Team(owner_id=principal.user_id, name=name)
            uow.teams.add(team)
            await _commit_name(uow)
            return await visible_team(uow, principal, team.id)

    async def get(self, principal: Principal, team_id: int) -> Team:
        async with self._uow_factory() as uow:
            return await visible_team(uow, principal, team_id)

    async def rename(self, principal: Principal, team_id: int, name: str) -> Team:
        async with self._uow_factory() as uow:
            team = await visible_team(uow, principal, team_id)
            if name == team.name:
                return team
            # Compruebo el nombre contra el dueño del equipo, también cuando lo renombra un admin
            await _require_free_name(uow, team.owner_id, name)
            team.name = name
            await _commit_name(uow)
            return await visible_team(uow, principal, team_id)

    async def delete(self, principal: Principal, team_id: int) -> None:
        async with self._uow_factory() as uow:
            team = await visible_team(uow, principal, team_id)
            logo_url = team.logo_url
            await uow.teams.delete(team)
            await uow.commit()
        # Borro el archivo después del commit: si el borrado del equipo fallara, el logo seguiría en uso
        await self._logo_files.discard(logo_url)


async def visible_team(uow: UnitOfWork, principal: Principal, team_id: int) -> Team:
    team = await uow.teams.get_team(team_id)
    # Respondo NOT_FOUND también con los equipos ajenos, para no revelar qué ids existen
    if team is None or (principal.role != UserRole.ADMIN and team.owner_id != principal.user_id):
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The team does not exist")
    return team


async def _require_free_name(uow: UnitOfWork, owner_id: int, name: str) -> None:
    if await uow.teams.name_taken(owner_id, name):
        raise _name_taken()


async def _commit_name(uow: UnitOfWork) -> None:
    try:
        await uow.commit()
    except IntegrityError as error:
        # Me apoyo en la restricción única (owner_id, name): dos altas simultáneas con el mismo nombre chocan aquí
        raise _name_taken() from error


def _name_taken() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_TEAM_NAME_TAKEN, "A team with that name already exists")
