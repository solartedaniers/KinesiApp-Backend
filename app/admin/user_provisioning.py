from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.admin.inputs import NewUserInput
from app.auth.auth_mailer import AuthMailer
from app.auth.one_time_codes import CodePurpose, OneTimeCodes
from app.auth.password_hasher import PasswordHasher
from app.core.domain_error import DomainError
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork


class UserProvisioning:
    """Doy de alta cuentas a pedido de un admin y le envío a su dueño el código para activarlas."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        hasher: PasswordHasher,
        codes: OneTimeCodes,
        mailer: AuthMailer,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._codes = codes
        self._mailer = mailer

    async def create(self, data: NewUserInput) -> User:
        async with self._uow_factory() as uow:
            # A diferencia del registro, no reemplazo una cuenta sin verificar: quizá su dueño espera el código
            if await uow.users.get_by_email(data.email) is not None:
                raise DomainError(ErrorReason.ERROR_REASON_EMAIL_ALREADY_REGISTERED, "The email is already registered")
            user = User(
                email=data.email,
                hashed_password=await self._hasher.hash(data.password),
                full_name=data.full_name,
                role=data.role,
                # Igual que en el registro: la verificación del correo es la que activa la cuenta
                is_active=False,
                is_verified=False,
            )
            code = await self._codes.assign(user, CodePurpose.VERIFICATION)
            uow.users.add(user)
            await uow.commit()
            await uow.users.refresh(user)
        # Si el correo falla la cuenta ya existe, y su dueño puede pedir otro código desde el login
        await self._mailer.send_verification_code(user.email, code)
        return user
