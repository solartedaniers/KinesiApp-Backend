from pydantic import Field

from app.settings.base import EnvSettings


class PaginationSettings(EnvSettings):
    """Tamaño de las páginas de los listados por cursor."""

    PAGE_SIZE_DEFAULT: int = Field(default=20, gt=0)
    PAGE_SIZE_MAX: int = Field(default=100, gt=0)
