from fastapi import Request, status
from fastapi.responses import JSONResponse


class AppException(Exception):
    """Excepción base de dominio: toda excepción de negocio hereda de esta."""

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        self.detail = detail
        self.status_code = status_code


class NotFoundException(AppException):
    """Recurso solicitado inexistente."""

    def __init__(self, resource: str, resource_id: object) -> None:
        super().__init__(
            detail=f"{resource} con id '{resource_id}' no fue encontrado",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflictException(AppException):
    """Violación de una regla de unicidad o de estado (p. ej. email duplicado)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, status_code=status.HTTP_409_CONFLICT)


class UnauthorizedException(AppException):
    """Credenciales inválidas o token de acceso ausente/expirado/mal formado."""

    def __init__(self, detail: str = "No autorizado") -> None:
        super().__init__(detail=detail, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenException(AppException):
    """El usuario está autenticado pero no cumple una condición de acceso (p. ej. email sin verificar)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, status_code=status.HTTP_403_FORBIDDEN)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    # Handler único registrado en main.py: da forma consistente a todos los errores de dominio
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
