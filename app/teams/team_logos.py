from collections.abc import Callable

from app.identity.principal import Principal
from app.models.team import Team
from app.repositories.unit_of_work import UnitOfWork
from app.storage.avatar_files import AvatarFiles, AvatarUpload
from app.storage.image_formats import ImageFormat
from app.storage.upload_tickets import UploadPurpose
from app.teams.team_catalog import visible_team


class TeamLogos:
    """Manejo el logo de un equipo con el mismo flujo de dos pasos que el avatar de una cuenta."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], files: AvatarFiles) -> None:
        self._uow_factory = uow_factory
        self._files = files

    async def create_upload(
        self, principal: Principal, team_id: int, image_format: ImageFormat, content_length: int
    ) -> AvatarUpload:
        # Compruebo el acceso antes de firmar nada: si no, cualquier coach podría subir al bucket
        async with self._uow_factory() as uow:
            await visible_team(uow, principal, team_id)
        return self._files.create_upload(team_id, UploadPurpose.TEAM_LOGO, image_format, content_length)

    async def confirm_upload(self, principal: Principal, team_id: int, upload_id: str) -> Team:
        new_url = await self._files.confirmed_url(team_id, UploadPurpose.TEAM_LOGO, upload_id)
        return await self._replace(principal, team_id, new_url)

    async def delete(self, principal: Principal, team_id: int) -> Team:
        return await self._replace(principal, team_id, None)

    async def _replace(self, principal: Principal, team_id: int, new_url: str | None) -> Team:
        async with self._uow_factory() as uow:
            team = await visible_team(uow, principal, team_id)
            previous_url = team.logo_url
            # Si confirman dos veces la misma subida, no borro el logo que acaba de quedar
            if previous_url == new_url:
                return team
            team.logo_url = new_url
            await uow.commit()
            team = await visible_team(uow, principal, team_id)
        await self._files.discard(previous_url)
        return team
