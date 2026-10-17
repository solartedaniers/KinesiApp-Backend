import enum
import secrets
from datetime import datetime, timedelta, timezone

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.auth.password_hasher import PasswordHasher
from app.core.domain_error import DomainError
from app.core.time_utils import is_expired
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork
from app.settings.auth import AuthSettings


class CodePurpose(enum.Enum):
    """Para qué es el código; el valor es el prefijo de sus columnas en users."""

    VERIFICATION = "verification_code"
    PASSWORD_RESET = "password_reset_code"


class OneTimeCodes:
    """Emite y comprueba los códigos de verificación y de recuperación, con vencimiento e intentos limitados."""

    def __init__(self, settings: AuthSettings, hasher: PasswordHasher) -> None:
        self._length = settings.OTP_LENGTH
        self._lifetime = timedelta(minutes=settings.OTP_EXPIRE_MINUTES)
        self._max_attempts = settings.OTP_MAX_ATTEMPTS
        self._hasher = hasher

    async def assign(self, user: User, purpose: CodePurpose) -> str:
        code = f"{secrets.randbelow(10**self._length):0{self._length}d}"
        # Guardo el hash: un volcado de la base no revela códigos vigentes
        self._set(user, purpose, await self._hasher.hash(code), datetime.now(timezone.utc) + self._lifetime, 0)
        return code

    async def check(self, uow: UnitOfWork, user: User, purpose: CodePurpose, code: str) -> None:
        code_hash: str | None = getattr(user, f"{purpose.value}_hash")
        expires_at: datetime | None = getattr(user, f"{purpose.value}_expires_at")
        attempts: int = getattr(user, f"{purpose.value}_attempts")
        if code_hash is None or expires_at is None or is_expired(expires_at) or attempts >= self._max_attempts:
            raise _invalid_code()
        if not await self._hasher.verify(code, code_hash):
            # Confirmo el intento fallido antes de responder: si no, probar códigos no tendría límite
            setattr(user, f"{purpose.value}_attempts", attempts + 1)
            await uow.commit()
            raise _invalid_code()

    def clear(self, user: User, purpose: CodePurpose) -> None:
        self._set(user, purpose, None, None, 0)

    @staticmethod
    def _set(user: User, purpose: CodePurpose, code_hash: str | None, expires_at: datetime | None, attempts: int) -> None:
        setattr(user, f"{purpose.value}_hash", code_hash)
        setattr(user, f"{purpose.value}_expires_at", expires_at)
        setattr(user, f"{purpose.value}_attempts", attempts)


def _invalid_code() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_INVALID_OTP, "Invalid or expired verification code")
