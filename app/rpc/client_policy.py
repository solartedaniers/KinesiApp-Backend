from kinesiapp.system.v1 import system_pb2

from app.identity.password_policy import PasswordPolicy
from app.settings.athlete import AthleteSettings
from app.settings.chat import ChatSettings
from app.settings.risk import RiskSettings
from app.settings.storage import MediaSettings


def build_client_policy(
    media: MediaSettings, passwords: PasswordPolicy, athletes: AthleteSettings, chat: ChatSettings, risk: RiskSettings
) -> system_pb2.GetClientPolicyResponse:
    # Lo armo una vez al arrancar: la configuración no cambia mientras el proceso vive
    return system_pb2.GetClientPolicyResponse(
        video_consent_version=media.VIDEO_CONSENT_VERSION,
        video=system_pb2.VideoPolicy(
            max_duration_seconds=media.MAX_VIDEO_DURATION_SECONDS, max_size_bytes=media.MAX_VIDEO_UPLOAD_BYTES
        ),
        max_avatar_size_bytes=media.MAX_AVATAR_UPLOAD_BYTES,
        password=system_pb2.PasswordPolicy(
            min_length=passwords.min_length,
            max_length=passwords.max_length,
            requirements=[
                system_pb2.PasswordRequirement.Value(f"PASSWORD_REQUIREMENT_{requirement.name}")
                for requirement in passwords.requirements
            ],
        ),
        athlete_min_age_years=athletes.ATHLETE_MIN_AGE_YEARS,
        athlete_max_age_years=athletes.ATHLETE_MAX_AGE_YEARS,
        chat_message_max_chars=chat.CHAT_MESSAGE_MAX_CHARS,
        biometrics=system_pb2.BiometricsPolicy(
            min_height_cm=athletes.ATHLETE_MIN_HEIGHT_CM,
            max_height_cm=athletes.ATHLETE_MAX_HEIGHT_CM,
            min_weight_kg=athletes.ATHLETE_MIN_WEIGHT_KG,
            max_weight_kg=athletes.ATHLETE_MAX_WEIGHT_KG,
        ),
        risk_scale=system_pb2.RiskScalePolicy(moderate_from=risk.RISK_LEVEL_MODERATE, high_from=risk.RISK_LEVEL_HIGH),
    )
