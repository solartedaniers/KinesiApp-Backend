from functools import lru_cache

from app.settings.athlete import AthleteSettings
from app.settings.auth import AuthSettings, PasswordPolicySettings
from app.settings.chat import ChatSettings
from app.settings.database import DatabaseSettings
from app.settings.http_api import HttpApiSettings
from app.settings.mail import MailSettings
from app.settings.pose import MovementPhaseSettings, PoseSettings
from app.settings.risk import RiskSettings
from app.settings.storage import MediaSettings, StorageSettings


class Settings(
    HttpApiSettings,
    DatabaseSettings,
    AuthSettings,
    PasswordPolicySettings,
    AthleteSettings,
    MailSettings,
    StorageSettings,
    MediaSettings,
    PoseSettings,
    MovementPhaseSettings,
    RiskSettings,
    ChatSettings,
):
    """Toda la configuración junta, para el código REST que todavía la lee de un solo objeto.

    El código gRPC nuevo recibe solo la clase de su dominio (app/settings/), no esta.
    """


@lru_cache
def get_settings() -> Settings:
    # La cacheo para no releer ni parsear el .env en cada inyección de dependencia
    return Settings()


settings = get_settings()
