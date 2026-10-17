import enum


class ImageFormat(enum.Enum):
    """Formatos de imagen admitidos para avatares, con su tipo MIME y la extensión de la clave del objeto."""

    JPEG = ("image/jpeg", ".jpg")
    PNG = ("image/png", ".png")
    WEBP = ("image/webp", ".webp")

    def __init__(self, mime_type: str, extension: str) -> None:
        self.mime_type = mime_type
        self.extension = extension

    @classmethod
    def from_mime_type(cls, mime_type: str) -> "ImageFormat":
        return next(image_format for image_format in cls if image_format.mime_type == mime_type)

    def matches(self, head: bytes) -> bool:
        # Magic bytes: el tipo declarado debe coincidir con el contenido real
        if self is ImageFormat.JPEG:
            return head.startswith(b"\xff\xd8\xff")
        if self is ImageFormat.PNG:
            return head.startswith(b"\x89PNG\r\n\x1a\n")
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


# Bytes iniciales que bastan para reconocer cualquiera de los formatos
SIGNATURE_LENGTH = 12
