"""Utilidades de fecha/hora sin dependencias hacia models: evita ciclos de import."""
from datetime import datetime, timezone


def is_expired(expires_at: datetime) -> bool:
    # SQLite (usada en tests) no conserva tzinfo al leer un DateTime(timezone=True);
    # se asume UTC si viene naive para poder comparar sin TypeError en cualquier motor
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)
