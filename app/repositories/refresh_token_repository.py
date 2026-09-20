from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.refresh_token import RefreshToken
from app.repositories.base_repository import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, RefreshToken)

    def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        return self._db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(timezone.utc)
        self._db.commit()

    def revoke_all_for_user(self, user_id: int) -> None:
        # Se invoca al cambiar la contraseña: cierra toda sesión activa del usuario
        self._db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        ).update({"revoked_at": datetime.now(timezone.utc)})
        self._db.commit()
