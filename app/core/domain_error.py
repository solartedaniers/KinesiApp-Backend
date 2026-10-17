from kinesiapp.common.v1.errors_pb2 import ErrorReason


class DomainError(Exception):
    """Error de negocio con su motivo del contrato; el interceptor de errores lo traduce a un status gRPC."""

    def __init__(self, reason: ErrorReason.ValueType, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
