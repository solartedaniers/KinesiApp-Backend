from collections.abc import Callable
from datetime import datetime, timezone

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.account.account_profile import own_account
from app.core.domain_error import DomainError
from app.models.user import User, UserRole
from app.repositories.unit_of_work import UnitOfWork

# Lo pido solo a quien sube videos: el deportista, o el coach por sus deportistas gestionados
_ROLES_THAT_UPLOAD = frozenset({UserRole.ATHLETE, UserRole.COACH})


class VideoConsent:
    """Registro que quien llama aceptó el texto vigente de consentimiento de video."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], current_version: int) -> None:
        self._uow_factory = uow_factory
        self._current_version = current_version

    async def grant(self, user_id: int, version: int) -> User:
        if version != self._current_version:
            raise DomainError(ErrorReason.ERROR_REASON_BAD_REQUEST, "Only the current consent version can be accepted")
        async with self._uow_factory() as uow:
            user = await own_account(uow, user_id)
            if user.role not in _ROLES_THAT_UPLOAD:
                raise DomainError(ErrorReason.ERROR_REASON_FORBIDDEN, "Only athletes and coaches upload videos")
            user.video_consent_given_at = datetime.now(timezone.utc)
            user.video_consent_version = version
            await uow.commit()
        return user
