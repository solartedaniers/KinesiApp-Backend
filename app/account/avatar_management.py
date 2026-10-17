import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.account.account_profile import own_account
from app.core.domain_error import DomainError
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork
from app.storage.image_formats import SIGNATURE_LENGTH, ImageFormat
from app.storage.signed_storage import PresignedUpload, SignedObjectStorage
from app.storage.upload_tickets import UploadPurpose, UploadTicket, UploadTicketService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AvatarUpload:
    upload_id: str
    target: PresignedUpload


class AvatarManagement:
    """Manejo el avatar de la propia cuenta: el navegador lo sube directo al bucket y yo solo firmo y verifico."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        storage: SignedObjectStorage,
        tickets: UploadTicketService,
        max_avatar_bytes: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._tickets = tickets
        self._max_avatar_bytes = max_avatar_bytes

    def create_upload(self, user_id: int, image_format: ImageFormat, content_length: int) -> AvatarUpload:
        key = f"avatars/{uuid.uuid4().hex}{image_format.extension}"
        target = self._storage.presign_upload(key, image_format.mime_type, content_length)
        ticket = UploadTicket(user_id, UploadPurpose.AVATAR, key, image_format.mime_type, content_length)
        return AvatarUpload(upload_id=self._tickets.issue(ticket), target=target)

    async def confirm_upload(self, user_id: int, upload_id: str) -> User:
        ticket = self._tickets.verify(upload_id, user_id, UploadPurpose.AVATAR)
        await self._ensure_valid_image(ticket)
        new_url = self._storage.url_for(ticket.key)
        async with self._uow_factory() as uow:
            user = await own_account(uow, user_id)
            previous_url = user.avatar_url
            # Si confirman dos veces la misma subida, no borro la foto que acaba de quedar
            if previous_url == new_url:
                return user
            user.avatar_url = new_url
            await uow.commit()
        await self._discard(previous_url)
        return user

    async def delete(self, user_id: int) -> User:
        async with self._uow_factory() as uow:
            user = await own_account(uow, user_id)
            previous_url = user.avatar_url
            user.avatar_url = None
            await uow.commit()
        await self._discard(previous_url)
        return user

    async def _ensure_valid_image(self, ticket: UploadTicket) -> None:
        stored = await self._storage.describe(ticket.key)
        if stored is None:
            raise DomainError(ErrorReason.ERROR_REASON_UPLOAD_NOT_FOUND, "The file was not uploaded")
        image_format = ImageFormat.from_mime_type(ticket.content_type)
        valid = (
            stored.size == ticket.content_length
            and stored.size <= self._max_avatar_bytes
            and image_format.matches(await self._storage.read_head(ticket.key, SIGNATURE_LENGTH))
        )
        if not valid:
            # Borro el objeto inválido para que no se quede ocupando espacio en el bucket
            await self._storage.delete(ticket.key)
            raise DomainError(ErrorReason.ERROR_REASON_INVALID_IMAGE, "The file is not the declared image")

    async def _discard(self, object_url: str | None) -> None:
        # Borro después de confirmar la base: si falla, solo queda un objeto huérfano, nunca una URL rota
        if object_url is None:
            return
        try:
            await self._storage.delete(self._storage.key_from_url(object_url))
        except (DomainError, ValueError) as error:
            logger.warning("Could not delete previous avatar %s: %s", object_url, error)
