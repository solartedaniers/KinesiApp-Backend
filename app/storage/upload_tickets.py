import enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from pydantic import BaseModel, ValidationError

from app.core.domain_error import DomainError
from app.settings.auth import AuthSettings


class UploadPurpose(str, enum.Enum):
    AVATAR = "avatar"
    # Lo emito a nombre del deportista gestionado: así el ticket no sirve para la foto de otro deportista del coach
    MANAGED_ATHLETE_AVATAR = "managed_athlete_avatar"
    ANALYSIS_VIDEO = "analysis_video"


@dataclass(frozen=True)
class UploadTicket:
    owner_id: int
    purpose: UploadPurpose
    key: str
    content_type: str
    content_length: int
    # Lo que el ticket fija además del archivo, por ejemplo el deportista y el movimiento de un video
    metadata: dict[str, str] = field(default_factory=dict)


class _TicketClaims(BaseModel):
    type: Literal["upload_ticket"]
    sub: int
    purpose: UploadPurpose
    key: str
    content_type: str
    content_length: int
    metadata: dict[str, str] = {}


class UploadTicketService:
    """Uso como upload_id un JWT firmado con lo que autoricé subir: así no guardo subidas pendientes en la base."""

    def __init__(self, settings: AuthSettings, lifetime_seconds: int) -> None:
        self._secret = settings.JWT_SECRET_KEY.get_secret_value()
        self._algorithm = settings.JWT_ALGORITHM
        self._lifetime = timedelta(seconds=lifetime_seconds)

    def issue(self, ticket: UploadTicket) -> str:
        claims = {
            "type": "upload_ticket",
            "sub": str(ticket.owner_id),
            "purpose": ticket.purpose.value,
            "key": ticket.key,
            "content_type": ticket.content_type,
            "content_length": ticket.content_length,
            "metadata": ticket.metadata,
            "exp": datetime.now(timezone.utc) + self._lifetime,
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)

    def verify(self, upload_id: str, owner_id: int, purpose: UploadPurpose) -> UploadTicket:
        try:
            claims = _TicketClaims.model_validate(jwt.decode(upload_id, self._secret, algorithms=[self._algorithm]))
        except (jwt.PyJWTError, ValidationError) as error:
            raise _upload_not_found() from error
        # Trato un ticket de otra persona o de otro tipo de archivo igual que uno inexistente
        if claims.sub != owner_id or claims.purpose is not purpose:
            raise _upload_not_found()
        return UploadTicket(owner_id, purpose, claims.key, claims.content_type, claims.content_length, claims.metadata)


def _upload_not_found() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_UPLOAD_NOT_FOUND, "The upload does not exist or has expired")
