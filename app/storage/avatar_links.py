import logging

from app.core.domain_error import DomainError
from app.storage.signed_storage import PresignedRead, SignedObjectStorage

logger = logging.getLogger(__name__)


class AvatarLinks:
    """Convierto la URL guardada de un avatar en una URL firmada de lectura y vida corta."""

    def __init__(self, storage: SignedObjectStorage) -> None:
        self._storage = storage

    def link(self, avatar_url: str | None) -> PresignedRead | None:
        if avatar_url is None:
            return None
        try:
            return self._storage.presign_read(self._storage.key_from_url(avatar_url))
        except (DomainError, ValueError) as error:
            # Sin bucket o con una URL ajena muestro la cuenta igual, solo sin foto
            logger.warning("Could not sign avatar %s: %s", avatar_url, error)
            return None
