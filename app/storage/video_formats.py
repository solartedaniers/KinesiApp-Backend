# Con estos bytes iniciales reconozco los contenedores que graban navegadores y celulares
VIDEO_SIGNATURE_LENGTH = 12


def looks_like_video(head: bytes) -> bool:
    """Compruebo los magic bytes del contenedor; que se pueda decodificar lo confirma la IA al analizarlo."""
    iso_media = head[4:8] == b"ftyp"  # MP4, MOV y 3GP
    matroska = head.startswith(b"\x1a\x45\xdf\xa3")  # WebM y MKV
    avi = head[:4] == b"RIFF" and head[8:12] == b"AVI "
    return iso_media or matroska or avi
