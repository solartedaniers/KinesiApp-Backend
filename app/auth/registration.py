import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.auth.auth_mailer import AuthMailer
from app.auth.inputs import RegisterInput
from app.auth.one_time_codes import CodePurpose, OneTimeCodes
from app.auth.password_hasher import PasswordHasher
from app.core.domain_error import DomainError
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork


class EmailDomainChecker(Protocol):
    def is_deliverable(self, email: str) -> bool: ...


class Registration:
    """Crea la cuenta sin verificar, con el consentimiento de video aceptado, y envía el código de verificación."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        hasher: PasswordHasher,
        codes: OneTimeCodes,
        mailer: AuthMailer,
        domain_checker: EmailDomainChecker,
        video_consent_version: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._codes = codes
        self._mailer = mailer
        self._domain_checker = domain_checker
        self._video_consent_version = video_consent_version

    async def register(self, data: RegisterInput) -> None:
        if data.accepted_video_consent_version != self._video_consent_version:
            raise DomainError(ErrorReason.ERROR_REASON_CONSENT_REQUIRED, "The current video consent must be accepted")
        # La consulta DNS bloquea: la hago en un hilo
        if not await asyncio.to_thread(self._domain_checker.is_deliverable, data.email):
            raise DomainError(
                ErrorReason.ERROR_REASON_EMAIL_DOMAIN_UNDELIVERABLE,
                "The email domain does not exist or does not accept email",
            )
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(data.email)
            if user is not None and user.is_verified:
                raise DomainError(ErrorReason.ERROR_REASON_EMAIL_ALREADY_REGISTERED, "The email is already registered")
            # Una cuenta sin verificar con el mismo correo se reemplaza: quizá perdió el código
            if user is None:
                user = User(email=data.email)
                uow.users.add(user)
            user.hashed_password = await self._hasher.hash(data.password)
            user.full_name = data.full_name
            user.role = data.role
            user.is_active = False
            user.is_verified = False
            user.video_consent_given_at = datetime.now(timezone.utc)
            user.video_consent_version = data.accepted_video_consent_version
            code = await self._codes.assign(user, CodePurpose.VERIFICATION)
            await uow.commit()
        await self._mailer.send_verification_code(data.email, code)
