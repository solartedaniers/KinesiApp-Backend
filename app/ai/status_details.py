from google.rpc import error_details_pb2, status_pb2


def error_reason(status: status_pb2.Status | None) -> str | None:
    """Busco el google.rpc.ErrorInfo entre los detalles del status y devuelvo su reason."""
    if status is None:
        return None
    for detail in status.details:
        info = error_details_pb2.ErrorInfo()
        if detail.Unpack(info):
            return info.reason
    return None
