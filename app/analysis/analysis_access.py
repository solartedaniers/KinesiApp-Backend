from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.athlete import AthleteProfile
from app.models.jump_analysis import JumpAnalysis
from app.models.user import UserRole
from app.repositories.unit_of_work import UnitOfWork


def can_see(principal: Principal, athlete: AthleteProfile) -> bool:
    """Ven los análisis de un deportista él mismo, su coach asignado y el admin."""
    return (
        principal.role == UserRole.ADMIN
        or (principal.role == UserRole.ATHLETE and athlete.user_id == principal.user_id)
        or (principal.role == UserRole.COACH and athlete.coach_id == principal.user_id)
    )


def manages_recordings(principal: Principal, athlete: AthleteProfile) -> bool:
    """Suben y borran el propio deportista y, si el deportista es gestionado (sin cuenta), su coach."""
    if principal.role == UserRole.ATHLETE:
        return athlete.user_id == principal.user_id
    return principal.role == UserRole.COACH and athlete.is_managed and athlete.coach_id == principal.user_id


async def visible_analysis(
    uow: UnitOfWork, principal: Principal, analysis_id: int, *, with_measurements: bool = False
) -> JumpAnalysis:
    repository = uow.analyses
    analysis = await (
        repository.get_with_measurements(analysis_id) if with_measurements else repository.get_with_athlete(analysis_id)
    )
    if analysis is None:
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The analysis does not exist")
    if not can_see(principal, analysis.athlete):
        raise DomainError(ErrorReason.ERROR_REASON_FORBIDDEN, "You cannot see this analysis")
    return analysis
