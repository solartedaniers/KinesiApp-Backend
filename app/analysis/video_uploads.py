import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from kinesiapp.common.v1.errors_pb2 import ErrorReason
from sqlalchemy.exc import IntegrityError

from app.analysis.analysis_access import manages_recordings
from app.analysis.analysis_runner import AnalysisRunner
from app.analysis.inputs import VideoUploadInput, VideoUploadRules
from app.athletes.profile_records import existing_athlete
from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus, MovementType
from app.repositories.unit_of_work import UnitOfWork
from app.storage.signed_storage import PresignedUpload, SignedObjectStorage
from app.storage.upload_tickets import UploadPurpose, UploadTicket, UploadTicketService
from app.storage.video_formats import VIDEO_SIGNATURE_LENGTH, looks_like_video

logger = logging.getLogger(__name__)

_ATHLETE = "athlete_id"
_MOVEMENT = "movement"


@dataclass(frozen=True)
class VideoUpload:
    upload_id: str
    target: PresignedUpload


class VideoUploads:
    """Firmo la subida de un video directo al bucket privado y, al confirmarla, creo el análisis y lo mando a procesar."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        videos: SignedObjectStorage,
        tickets: UploadTicketService,
        rules: VideoUploadRules,
        consent_version: int,
        runner: AnalysisRunner,
    ) -> None:
        self._uow_factory = uow_factory
        self._videos = videos
        self._tickets = tickets
        self._rules = rules
        self._consent_version = consent_version
        self._runner = runner

    async def create_upload(self, principal: Principal, upload: VideoUploadInput) -> VideoUpload:
        self._rules.check(upload)
        async with self._uow_factory() as uow:
            await self._ensure_may_record(uow, principal, upload.athlete_id)
            uploader = await uow.users.get(principal.user_id)
        # Exijo el consentimiento vigente de quien sube, sea el deportista o el coach de uno gestionado
        if uploader is None or uploader.video_consent_given_at is None or uploader.video_consent_version != self._consent_version:
            raise DomainError(ErrorReason.ERROR_REASON_CONSENT_REQUIRED, "Accept the current video consent before uploading")
        key = f"videos/{upload.athlete_id}/{uuid.uuid4().hex}"
        target = self._videos.presign_upload(key, upload.content_type, upload.content_length)
        metadata = {_ATHLETE: str(upload.athlete_id), _MOVEMENT: upload.movement_type.name}
        ticket = UploadTicket(principal.user_id, UploadPurpose.ANALYSIS_VIDEO, key, upload.content_type, upload.content_length, metadata)
        return VideoUpload(self._tickets.issue(ticket), target)

    async def confirm_upload(self, principal: Principal, upload_id: str) -> JumpAnalysis:
        ticket = self._tickets.verify(upload_id, principal.user_id, UploadPurpose.ANALYSIS_VIDEO)
        athlete_id = int(ticket.metadata[_ATHLETE])
        video_reference = self._videos.url_for(ticket.key)
        async with self._uow_factory() as uow:
            # Si confirman dos veces la misma subida, devuelvo el mismo análisis y no creo otro
            existing = await uow.analyses.find_by_video(video_reference)
            if existing is not None:
                return existing
            # Vuelvo a mirar el permiso: entre la firma y la confirmación pudo cambiar el coach o la cuenta
            await self._ensure_may_record(uow, principal, athlete_id)
        await self._ensure_valid_video(ticket)
        try:
            async with self._uow_factory() as uow:
                analysis = JumpAnalysis(
                    athlete_id=athlete_id,
                    video_reference=video_reference,
                    movement_type=MovementType[ticket.metadata[_MOVEMENT]],
                    status=JumpAnalysisStatus.PENDING,
                )
                uow.analyses.add(analysis)
                await uow.commit()
                created = await uow.analyses.get_with_athlete(analysis.id)
        except IntegrityError:
            # Otra confirmación simultánea de la misma subida ganó la fila única: devuelvo la suya
            async with self._uow_factory() as uow:
                winner = await uow.analyses.find_by_video(video_reference)
            if winner is None:
                raise
            return winner
        self._runner.submit(created.id)
        return created

    @staticmethod
    async def _ensure_may_record(uow: UnitOfWork, principal: Principal, athlete_id: int) -> None:
        athlete = await existing_athlete(uow, athlete_id)
        if not manages_recordings(principal, athlete):
            raise DomainError(ErrorReason.ERROR_REASON_FORBIDDEN, "You cannot upload videos for this athlete")

    async def _ensure_valid_video(self, ticket: UploadTicket) -> None:
        stored = await self._videos.describe(ticket.key)
        if stored is None:
            raise DomainError(ErrorReason.ERROR_REASON_UPLOAD_NOT_FOUND, "The video was not uploaded")
        valid = (
            stored.size == ticket.content_length
            and stored.content_type == ticket.content_type
            and looks_like_video(await self._videos.read_head(ticket.key, VIDEO_SIGNATURE_LENGTH))
        )
        if not valid:
            # Borro lo que no es el video declarado para que no se quede ocupando el bucket
            await self._videos.delete(ticket.key)
            logger.warning("Rejected upload %s: size or content does not match", ticket.key)
            raise DomainError(ErrorReason.ERROR_REASON_INVALID_VIDEO, "The file is not the declared video")
