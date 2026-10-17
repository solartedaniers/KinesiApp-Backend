from app.auth.session_tokens import SessionTokens, SessionTokenService
from app.models.refresh_token import RefreshToken
from app.repositories.unit_of_work import UnitOfWork


class SessionIssuer:
    """Abre una sesión: firma el par de tokens y registra el refresh token para poder revocarlo."""

    def __init__(self, tokens: SessionTokenService) -> None:
        self._tokens = tokens

    def open(self, uow: UnitOfWork, user_id: int) -> SessionTokens:
        session = self._tokens.issue(user_id)
        uow.refresh_tokens.add(
            RefreshToken(
                user_id=user_id,
                token_hash=self._tokens.fingerprint(session.refresh_token),
                expires_at=session.refresh_token_expires_at,
            )
        )
        return session
