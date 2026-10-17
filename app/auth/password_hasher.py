import asyncio

from passlib.context import CryptContext


class PasswordHasher:
    """Uso bcrypt, el mismo esquema del REST, para que las contraseñas y los códigos guardados sigan sirviendo."""

    def __init__(self) -> None:
        self._context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # bcrypt tarda cientos de milisegundos a propósito: lo saco a un hilo para no frenar el event loop
    async def hash(self, secret: str) -> str:
        return await asyncio.to_thread(self._context.hash, secret)

    async def verify(self, secret: str, secret_hash: str) -> bool:
        try:
            return await asyncio.to_thread(self._context.verify, secret, secret_hash)
        except (ValueError, TypeError):
            return False
