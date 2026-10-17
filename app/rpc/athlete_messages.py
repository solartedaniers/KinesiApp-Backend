from datetime import date
from typing import Any

from kinesiapp.athlete.v1 import athlete_pb2
from kinesiapp.common.v1 import date_pb2

from app.models.athlete import AthleteProfile, Gender
from app.rpc.proto_values import signed_url
from app.storage.avatar_links import AvatarLinks

_GENDER_PREFIX = "GENDER_"


class AthleteMessages:
    """Traduzco entre la ficha guardada y los mensajes de kinesiapp.athlete.v1, con el avatar ya firmado."""

    def __init__(self, avatar_links: AvatarLinks) -> None:
        self._avatar_links = avatar_links

    def profile(self, athlete: AthleteProfile) -> athlete_pb2.AthleteProfile:
        message = athlete_pb2.AthleteProfile(
            id=athlete.id,
            display_name=athlete.display_name,
            is_managed=athlete.is_managed,
            biometrics=athlete_pb2.Biometrics(
                gender=_gender_to_proto(athlete.gender),
                height_cm=athlete.height_cm,
                weight_kg=athlete.weight_kg,
                birth_date=_calendar_date(athlete.birth_date),
            ),
        )
        if athlete.user_id is not None:
            message.user_id = athlete.user_id
        if athlete.coach_id is not None:
            message.coach_id = athlete.coach_id
            message.coach_name = athlete.coach_name
        avatar = self._avatar_links.link(athlete.display_avatar)
        if avatar is not None:
            message.avatar.CopyFrom(signed_url(avatar))
        return message


def biometrics_fields(biometrics: athlete_pb2.Biometrics) -> dict[str, Any]:
    return {
        "gender": gender_from_proto(biometrics.gender),
        "height_cm": biometrics.height_cm,
        "weight_kg": biometrics.weight_kg,
        "birth_date": birth_date_from_proto(biometrics.birth_date) if biometrics.HasField("birth_date") else None,
    }


def biometrics_update_fields(update: athlete_pb2.BiometricsUpdate) -> dict[str, Any]:
    # Paso solo los campos presentes: así la edición parcial distingue "no lo cambio" de un valor inválido
    fields: dict[str, Any] = {}
    if update.HasField("gender"):
        fields["gender"] = gender_from_proto(update.gender)
    if update.HasField("height_cm"):
        fields["height_cm"] = update.height_cm
    if update.HasField("weight_kg"):
        fields["weight_kg"] = update.weight_kg
    if update.HasField("birth_date"):
        fields["birth_date"] = birth_date_from_proto(update.birth_date)
    return fields


def gender_from_proto(gender: athlete_pb2.Gender.ValueType) -> Gender | None:
    # Devuelvo None para GENDER_UNSPECIFIED y el validador lo reporta como campo inválido
    return Gender.__members__.get(athlete_pb2.Gender.Name(gender).removeprefix(_GENDER_PREFIX))


def birth_date_from_proto(value: date_pb2.CalendarDate) -> date | str:
    try:
        return date(value.year, value.month, value.day)
    except ValueError:
        # Devuelvo el texto tal cual para que el validador lo reporte como fecha inválida en su campo
        return f"{value.year}-{value.month}-{value.day}"


def _gender_to_proto(gender: Gender) -> athlete_pb2.Gender.ValueType:
    return athlete_pb2.Gender.Value(f"{_GENDER_PREFIX}{gender.name}")


def _calendar_date(value: date) -> date_pb2.CalendarDate:
    return date_pb2.CalendarDate(year=value.year, month=value.month, day=value.day)
