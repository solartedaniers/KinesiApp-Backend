from pydantic import Field, SecretStr
from sqlalchemy.engine import URL

from app.settings.base import EnvSettings


class DatabaseSettings(EnvSettings):
    """Configuro la conexión a Neon sin defaults: si faltan, la app no arranca en vez de buscar otro Postgres."""

    # En local uso el endpoint directo; en Render, el "-pooler"
    POSTGRES_USER: str = Field(min_length=1)
    POSTGRES_PASSWORD: SecretStr = Field(min_length=1)
    POSTGRES_HOST: str = Field(min_length=1)
    POSTGRES_PORT: int = Field(default=5432, gt=0, le=65535)
    POSTGRES_DB: str = Field(min_length=1)
    # Neon exige TLS. Lo paso explícito a los dos drivers: asyncpg no lee PGSSLMODE y libpq no lo lee del .env
    POSTGRES_SSL_MODE: str = Field(default="require", min_length=1)

    @property
    def database_url(self) -> URL:
        return self._url("postgresql+psycopg2").update_query_dict({"sslmode": self.POSTGRES_SSL_MODE})

    @property
    def async_database_url(self) -> URL:
        return self._url("postgresql+asyncpg")

    def _url(self, drivername: str) -> URL:
        # Uso URL.create porque escapa bien las credenciales con @, :, / o %
        return URL.create(
            drivername=drivername,
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )
