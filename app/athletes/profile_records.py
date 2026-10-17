from kinesiapp.common.v1.errors_pb2 import ErrorReason
from sqlalchemy.exc import IntegrityError

from app.athletes.inputs import BiometricsInput
from app.core.domain_error import DomainError
from app.models.athlete import AthleteProfile
from app.repositories.unit_of_work import UnitOfWork


async def existing_athlete(uow: UnitOfWork, athlete_id: int) -> AthleteProfile:
    athlete = await uow.athletes.get_profile(athlete_id)
    if athlete is None:
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The athlete does not exist")
    return athlete


async def open_profile(uow: UnitOfWork, user_id: int, biometrics: BiometricsInput) -> AthleteProfile:
    if await uow.athletes.get_by_user_id(user_id) is not None:
        raise _profile_exists()
    profile = AthleteProfile(user_id=user_id, **biometrics.model_dump())
    uow.athletes.add(profile)
    try:
        await uow.commit()
    except IntegrityError as error:
        # Me apoyo en que user_id es única: si dos altas llegan a la vez, la segunda choca aquí y no queda duplicada
        raise _profile_exists() from error
    return await existing_athlete(uow, profile.id)


def _profile_exists() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_PROFILE_ALREADY_EXISTS, "The account already has an athlete profile")
