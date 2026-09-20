import enum

from fastapi import Request, status
from fastapi.responses import JSONResponse


class ErrorCode(str, enum.Enum):
    """Código estable por escenario de negocio: el cliente traduce por code, no por detail."""

    BAD_REQUEST = "bad_request"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    EMAIL_ALREADY_REGISTERED = "email_already_registered"
    PROFILE_ALREADY_EXISTS = "profile_already_exists"
    INVALID_CREDENTIALS = "invalid_credentials"
    ACCOUNT_DISABLED = "account_disabled"
    EMAIL_NOT_VERIFIED = "email_not_verified"
    INVALID_OTP = "invalid_otp"
    INVALID_REFRESH_TOKEN = "invalid_refresh_token"
    INVALID_ROLE_ASSIGNMENT = "invalid_role_assignment"


class AppException(Exception):
    """Excepción base de dominio: toda excepción de negocio hereda de esta."""

    def __init__(
        self,
        detail: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: ErrorCode = ErrorCode.BAD_REQUEST,
    ) -> None:
        self.detail = detail
        self.status_code = status_code
        self.code = code


class NotFoundException(AppException):
    """Recurso solicitado inexistente."""

    def __init__(self, resource: str, resource_id: object, code: ErrorCode = ErrorCode.NOT_FOUND) -> None:
        super().__init__(
            detail=f"{resource} with id '{resource_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
            code=code,
        )


class ConflictException(AppException):
    """Violación de una regla de unicidad o de estado (p. ej. email duplicado)."""

    def __init__(self, detail: str, code: ErrorCode = ErrorCode.CONFLICT) -> None:
        super().__init__(detail=detail, status_code=status.HTTP_409_CONFLICT, code=code)


class UnauthorizedException(AppException):
    """Credenciales inválidas o token de acceso ausente/expirado/mal formado."""

    def __init__(self, detail: str = "Not authorized", code: ErrorCode = ErrorCode.UNAUTHORIZED) -> None:
        super().__init__(detail=detail, status_code=status.HTTP_401_UNAUTHORIZED, code=code)


class ForbiddenException(AppException):
    """El usuario está autenticado pero no cumple una condición de acceso (p. ej. email sin verificar)."""

    def __init__(self, detail: str, code: ErrorCode = ErrorCode.FORBIDDEN) -> None:
        super().__init__(detail=detail, status_code=status.HTTP_403_FORBIDDEN, code=code)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    # Handler único registrado en main.py: da forma consistente a todos los errores de dominio
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code.value})
