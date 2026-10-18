"""Pruebo AnalysisService por la red: subida firmada, confirmación, procesamiento en segundo plano con
reintentos, seguimiento en vivo, consultas, borrado y la recuperación del arranque."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import grpc
from kinesiapp.ai.v1 import movement_analysis_pb2
from kinesiapp.analysis.v1 import analysis_pb2, analysis_pb2_grpc
from kinesiapp.common.v1 import movement_pb2, pagination_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from sqlalchemy import func, select

from app.ai.remote_movement_analyzer import AnalyzerError
from app.analysis.analysis_catalog import AnalysisCatalog
from app.analysis.analysis_processing import AnalysisProcessing
from app.analysis.analysis_recovery import StalledAnalysisRecovery
from app.analysis.analysis_removal import AnalysisRemoval
from app.analysis.analysis_runner import AnalysisRunner
from app.analysis.analysis_watch import AnalysisWatch
from app.analysis.inputs import VideoUploadRules
from app.analysis.progress import AnalysisProgressUpdate
from app.analysis.progress_hub import AnalysisProgressHub
from app.analysis.retry_policy import RetryPolicy
from app.analysis.risk_assessment_codec import RiskAssessmentCodec
from app.analysis.risk_level import RiskLevelClassifier
from app.analysis.video_playback import VideoPlayback
from app.analysis.video_uploads import VideoUploads
from app.core.pagination import PageRules
from app.models.athlete import AthleteProfile, Gender
from app.models.jump_analysis import AnalysisStage, JumpAnalysis, JumpAnalysisStatus, MovementType
from app.models.user import User, UserRole
from app.rpc.analysis_messages import AnalysisMessages
from app.rpc.analysis_servicer import AnalysisServicer
from app.storage.upload_tickets import UploadTicketService
from tests.grpc_harness import error_info, field_violations
from tests.rpc_world import AUTH_SETTINGS, BUCKET_URL, FakeBucket, World, bearer, rpc_world, uow_factory

SAMPLE = json.loads((Path(__file__).parent / "risk_details_sample.json").read_text(encoding="utf-8"))
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
CONSENT_VERSION = 2
MAX_BYTES = 1_000
MAX_DURATION_MS = 40_000
MAX_ATTEMPTS = 3
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _result() -> movement_analysis_pb2.MovementAnalysisResult:
    return movement_analysis_pb2.MovementAnalysisResult(
        angle_samples=[
            movement_pb2.JointAngleSample(joint=movement_pb2.JOINT_ANGLE_KNEE_FLEXION, angle_degrees=95.0, frame_timestamp_ms=33),
            movement_pb2.JointAngleSample(joint=movement_pb2.JOINT_ANGLE_TRUNK_INCLINATION, angle_degrees=20.0, frame_timestamp_ms=0),
        ],
        risk_assessment=RiskAssessmentCodec().to_assessment(SAMPLE, movement_pb2.RISK_LEVEL_HIGH),
        pose_model_version="pose-v1",
        risk_model_version="risk-v1",
    )


class _FakeAnalyzer:
    """Simulo la IA en memoria: cada llamada sigue el guion que le toca; "ok" espera a que la prueba suelte la compuerta."""

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.calls: list[str] = []
        self.gate = asyncio.Event()
        self.gate.set()
        self.started = asyncio.Event()

    async def analyze(self, video_url: str, movement_type: MovementType):
        self.calls.append(video_url)
        step = self.script[min(len(self.calls), len(self.script)) - 1]
        if step == "busy":
            raise AnalyzerError("AI_BUSY", True, "busy")
        if step == "unreadable":
            raise AnalyzerError("VIDEO_UNREADABLE", False, "bad video")
        yield AnalysisProgressUpdate(AnalysisStage.EXTRACTING_POSE, 10, 100)
        self.started.set()
        await self.gate.wait()
        yield AnalysisProgressUpdate(AnalysisStage.SCORING_RISK)
        yield _result()


@dataclass
class _Lab:
    world: World
    stub: analysis_pb2_grpc.AnalysisServiceStub
    bucket: FakeBucket
    analyzer: _FakeAnalyzer
    runner: AnalysisRunner
    recovery: StalledAnalysisRecovery
    delays: list[float] = field(default_factory=list)


def _run(tmp_path: Path, scenario, script: list[str] | None = None):
    bucket = FakeBucket()
    analyzer = _FakeAnalyzer(script or ["ok"])
    parts: dict = {}

    def register(session_factory):
        uows = uow_factory(session_factory)
        hub = AnalysisProgressHub()
        codec, levels = RiskAssessmentCodec(), RiskLevelClassifier(0.33, 0.66)
        delays: list[float] = []

        async def sleep(seconds: float) -> None:
            delays.append(seconds)

        processing = AnalysisProcessing(
            uows, bucket, analyzer, hub, codec, RetryPolicy(MAX_ATTEMPTS, 5.0, 2.0, 60.0), 0.0, lambda: NOW, sleep
        )
        runner = AnalysisRunner(processing.process, 1)
        parts.update(runner=runner, delays=delays, recovery=StalledAnalysisRecovery(uows, runner, 120.0, lambda: NOW))
        servicer = AnalysisServicer(
            PageRules(default_size=10, max_size=50),
            VideoUploads(
                uows, bucket, UploadTicketService(AUTH_SETTINGS, 60), VideoUploadRules(MAX_BYTES, MAX_DURATION_MS),
                CONSENT_VERSION, runner,
            ),
            AnalysisWatch(uows, hub),
            AnalysisCatalog(uows),
            AnalysisRemoval(uows, bucket, runner, hub),
            VideoPlayback(uows, bucket),
            AnalysisMessages(codec, levels),
        )
        return partial(analysis_pb2_grpc.add_AnalysisServiceServicer_to_server, servicer)

    async def main():
        async with rpc_world(tmp_path / "analysis.db", register) as world:
            lab = _Lab(world, analysis_pb2_grpc.AnalysisServiceStub(world.channel), bucket, analyzer,
                       parts["runner"], parts["recovery"], parts["delays"])
            try:
                return await scenario(lab)
            finally:
                await lab.runner.aclose()

    return asyncio.run(main())


@dataclass
class _People:
    athlete: User
    profile_id: int
    coach: User
    managed_id: int
    stranger: User


async def _people(world: World) -> _People:
    consent = {"video_consent_given_at": NOW, "video_consent_version": CONSENT_VERSION}
    coach = await world.user("coach@kinesiapp.com", UserRole.COACH, **consent)
    athlete = await world.user("atleta@kinesiapp.com", UserRole.ATHLETE, **consent)
    stranger = await world.user("otro@kinesiapp.com", UserRole.ATHLETE, **consent)
    async with world.session_factory() as session:
        own = AthleteProfile(
            user_id=athlete.id, coach_id=coach.id, gender=Gender.FEMALE, height_cm=165, weight_kg=60, birth_date=date(2002, 5, 6)
        )
        managed = AthleteProfile(
            full_name="Juan Gestionado", coach_id=coach.id, gender=Gender.MALE, height_cm=170, weight_kg=70,
            birth_date=date(2001, 1, 1),
        )
        session.add_all([own, managed])
        await session.commit()
        return _People(athlete, own.id, coach, managed.id, stranger)


def _upload_request(athlete_id: int, **overrides) -> analysis_pb2.CreateVideoUploadRequest:
    values = {
        "athlete_id": athlete_id,
        "movement_type": movement_pb2.MOVEMENT_TYPE_SQUAT,
        "content_type": "video/mp4",
        "content_length": len(MP4),
        "duration_ms": 39_900,
    } | overrides
    return analysis_pb2.CreateVideoUploadRequest(**values)


async def _upload(lab: _Lab, user: User, athlete_id: int, content: bytes = MP4) -> str:
    created = await lab.stub.CreateVideoUpload(_upload_request(athlete_id), metadata=bearer(user))
    key = lab.bucket.signed_uploads[-1][0]
    lab.bucket.browser_put(key, content, "video/mp4")
    return created.upload_id


async def _confirm(lab: _Lab, user: User, upload_id: str) -> analysis_pb2.AnalysisSummary:
    request = analysis_pb2.ConfirmVideoUploadRequest(upload_id=upload_id)
    return (await lab.stub.ConfirmVideoUpload(request, metadata=bearer(user))).analysis


async def _watch(lab: _Lab, user: User, analysis_id: int) -> tuple[list, grpc.aio.AioRpcError | None]:
    received = []
    try:
        async for reply in lab.stub.WatchAnalysis(analysis_pb2.WatchAnalysisRequest(analysis_id=analysis_id), metadata=bearer(user)):
            received.append(reply)
    except grpc.aio.AioRpcError as error:
        return received, error
    return received, None


async def _failure(call) -> grpc.aio.AioRpcError:
    try:
        await call
    except grpc.aio.AioRpcError as error:
        return error
    raise AssertionError("The call should have failed")


def _reason(name: str) -> int:
    return ErrorReason.Value(f"ERROR_REASON_{name}")


async def _stored(lab: _Lab, analysis_id: int) -> JumpAnalysis | None:
    async with lab.world.session_factory() as session:
        return await session.get(JumpAnalysis, analysis_id)


def test_the_athlete_uploads_follows_reads_plays_and_deletes_an_analysis(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        summary = await _confirm(lab, people.athlete, await _upload(lab, people.athlete, people.profile_id))
        events, error = await _watch(lab, people.athlete, summary.id)
        detail = await lab.stub.GetAnalysis(analysis_pb2.GetAnalysisRequest(analysis_id=summary.id), metadata=bearer(people.athlete))
        video = await lab.stub.GetVideoPlaybackUrl(
            analysis_pb2.GetVideoPlaybackUrlRequest(analysis_id=summary.id), metadata=bearer(people.coach)
        )
        listed = await lab.stub.ListAthleteAnalyses(
            analysis_pb2.ListAthleteAnalysesRequest(athlete_id=people.profile_id), metadata=bearer(people.athlete)
        )
        objects_before = set(lab.bucket.objects)
        await lab.stub.DeleteAnalysis(analysis_pb2.DeleteAnalysisRequest(analysis_id=summary.id), metadata=bearer(people.athlete))
        gone = await _failure(lab.stub.GetAnalysis(analysis_pb2.GetAnalysisRequest(analysis_id=summary.id), metadata=bearer(people.athlete)))
        return summary, events, error, detail.analysis, video.video, listed, objects_before, lab, gone

    summary, events, error, detail, video, listed, objects_before, lab, gone = _run(tmp_path, scenario)

    assert summary.status == movement_pb2.ANALYSIS_STATUS_PENDING
    assert summary.movement_type == movement_pb2.MOVEMENT_TYPE_SQUAT
    assert error is None and events[-1].HasField("finished") and all(e.HasField("progress") for e in events[:-1])
    finished = events[-1].finished
    assert finished.status == movement_pb2.ANALYSIS_STATUS_PROCESSED and finished.risk_level == movement_pb2.RISK_LEVEL_HIGH
    assert finished.dominant_risk_pattern == "forward_collapse"
    assert [sample.frame_timestamp_ms for sample in detail.angle_samples] == [0, 33]
    assert detail.angle_samples[0].joint == movement_pb2.JOINT_ANGLE_TRUNK_INCLINATION
    assert detail.risk_assessment.dominant_pattern == "forward_collapse" and detail.pose_model_version == "pose-v1"
    # Compruebo que a la IA le llegue una URL firmada de lectura, nunca la canónica del bucket privado
    assert lab.analyzer.calls[0].endswith("?signature=get")
    assert video.url.startswith(BUCKET_URL + "videos/") and video.url.endswith("?signature=get")
    assert [item.id for item in listed.analyses] == [summary.id] and listed.page.next_page_token == ""
    assert len(objects_before) == 1 and lab.bucket.objects == {}
    assert gone.code() is grpc.StatusCode.NOT_FOUND


def test_uploads_require_permission_current_consent_and_the_video_limits(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        stub = lab.stub
        async with lab.world.session_factory() as session:
            athlete = await session.get(User, people.athlete.id)
            athlete.video_consent_version = CONSENT_VERSION - 1
            await session.commit()
        return {
            "old_consent": await _failure(stub.CreateVideoUpload(_upload_request(people.profile_id), metadata=bearer(people.athlete))),
            "stranger": await _failure(stub.CreateVideoUpload(_upload_request(people.profile_id), metadata=bearer(people.stranger))),
            # Al coach solo lo dejo subir por sus deportistas gestionados; el que tiene cuenta sube él mismo
            "coach_own": await _failure(stub.CreateVideoUpload(_upload_request(people.profile_id), metadata=bearer(people.coach))),
            "too_large": await _failure(
                stub.CreateVideoUpload(_upload_request(people.managed_id, content_length=MAX_BYTES + 1), metadata=bearer(people.coach))
            ),
            "too_long": await _failure(
                stub.CreateVideoUpload(_upload_request(people.managed_id, duration_ms=MAX_DURATION_MS + 1), metadata=bearer(people.coach))
            ),
            "not_video": await _failure(
                stub.CreateVideoUpload(_upload_request(people.managed_id, content_type="image/png"), metadata=bearer(people.coach))
            ),
            "no_movement": await _failure(
                stub.CreateVideoUpload(
                    _upload_request(people.managed_id, movement_type=movement_pb2.MOVEMENT_TYPE_UNSPECIFIED), metadata=bearer(people.coach)
                )
            ),
            "managed": await stub.CreateVideoUpload(_upload_request(people.managed_id), metadata=bearer(people.coach)),
        }

    outcome = _run(tmp_path, scenario)

    assert error_info(outcome["old_consent"]).reason == "CONSENT_REQUIRED"
    assert error_info(outcome["stranger"]).reason == "FORBIDDEN"
    assert error_info(outcome["coach_own"]).reason == "FORBIDDEN"
    assert error_info(outcome["too_large"]).reason == "VIDEO_TOO_LARGE"
    assert error_info(outcome["too_long"]).reason == "VIDEO_TOO_LONG"
    assert error_info(outcome["not_video"]).reason == "INVALID_VIDEO"
    assert field_violations(outcome["no_movement"]) == ["movement_type"]
    assert outcome["managed"].upload_id and outcome["managed"].target.headers["Content-Type"] == "video/mp4"


def test_confirming_checks_the_object_and_deletes_what_is_not_the_declared_video(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        created = await lab.stub.CreateVideoUpload(_upload_request(people.profile_id), metadata=bearer(people.athlete))
        missing = await _failure(lab.stub.ConfirmVideoUpload(
            analysis_pb2.ConfirmVideoUploadRequest(upload_id=created.upload_id), metadata=bearer(people.athlete)
        ))
        fake = b"<html>" + b"x" * (len(MP4) - 6)
        lab.bucket.browser_put(lab.bucket.signed_uploads[-1][0], fake, "video/mp4")
        invalid = await _failure(lab.stub.ConfirmVideoUpload(
            analysis_pb2.ConfirmVideoUploadRequest(upload_id=created.upload_id), metadata=bearer(people.athlete)
        ))
        foreign = await _failure(lab.stub.ConfirmVideoUpload(
            analysis_pb2.ConfirmVideoUploadRequest(upload_id=created.upload_id), metadata=bearer(people.stranger)
        ))
        async with lab.world.session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(JumpAnalysis))
        return missing, invalid, foreign, lab.bucket.objects, count

    missing, invalid, foreign, objects, count = _run(tmp_path, scenario)

    assert error_info(missing).reason == "UPLOAD_NOT_FOUND"
    assert error_info(invalid).reason == "INVALID_VIDEO" and objects == {}
    # Ato el ticket a quien pidió la subida: otra cuenta no puede confirmarlo
    assert error_info(foreign).reason == "UPLOAD_NOT_FOUND"
    assert count == 0


def test_two_simultaneous_confirmations_create_a_single_analysis(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        upload_id = await _upload(lab, people.athlete, people.profile_id)
        first, second = await asyncio.gather(
            _confirm(lab, people.athlete, upload_id), _confirm(lab, people.athlete, upload_id)
        )
        again = await _confirm(lab, people.athlete, upload_id)
        await _watch(lab, people.athlete, first.id)
        async with lab.world.session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(JumpAnalysis))
        return first.id, second.id, again.id, count, lab.analyzer.calls

    first, second, again, count, calls = _run(tmp_path, scenario)

    assert first == second == again and count == 1 and len(calls) == 1


def test_a_late_watcher_gets_the_persisted_progress_and_then_the_live_one(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        lab.analyzer.gate.clear()
        summary = await _confirm(lab, people.athlete, await _upload(lab, people.athlete, people.profile_id))
        await lab.analyzer.started.wait()
        watching = asyncio.create_task(_watch(lab, people.coach, summary.id))
        await asyncio.sleep(0.2)
        lab.analyzer.gate.set()
        events, error = await watching
        after, _ = await _watch(lab, people.coach, summary.id)
        stranger = await _failure(lab.stub.GetAnalysis(analysis_pb2.GetAnalysisRequest(analysis_id=summary.id), metadata=bearer(people.stranger)))
        return events, error, after, stranger

    events, error, after, stranger = _run(tmp_path, scenario)

    assert error is None
    assert events[0].progress.stage == movement_pb2.ANALYSIS_STAGE_EXTRACTING_POSE and events[0].progress.frames_total == 100
    assert events[-1].finished.status == movement_pb2.ANALYSIS_STATUS_PROCESSED
    # Si ya terminó, entrego solo el resultado y cierro el stream
    assert len(after) == 1 and after[0].HasField("finished")
    assert error_info(stranger).reason == "FORBIDDEN"


def test_a_busy_ai_is_retried_with_growing_delays_until_it_answers(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        summary = await _confirm(lab, people.athlete, await _upload(lab, people.athlete, people.profile_id))
        events, _ = await _watch(lab, people.athlete, summary.id)
        return events[-1].finished, await _stored(lab, summary.id), lab.delays, lab.analyzer.calls

    finished, stored, delays, calls = _run(tmp_path, scenario, ["busy", "busy", "ok"])

    assert finished.status == movement_pb2.ANALYSIS_STATUS_PROCESSED
    assert stored.attempts == 3 and len(calls) == 3 and delays == [5.0, 10.0]


def test_retries_stop_when_the_attempts_run_out_or_the_failure_is_permanent(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        summary = await _confirm(lab, people.athlete, await _upload(lab, people.athlete, people.profile_id))
        events, _ = await _watch(lab, people.athlete, summary.id)
        return events[-1].finished, len(lab.analyzer.calls)

    (tmp_path / "busy").mkdir()
    exhausted, exhausted_calls = _run(tmp_path / "busy", scenario, ["busy"])
    permanent, permanent_calls = _run(tmp_path, scenario, ["unreadable"])

    assert exhausted.status == movement_pb2.ANALYSIS_STATUS_FAILED and exhausted_calls == MAX_ATTEMPTS
    assert exhausted.failure_reason == _reason("AI_BUSY")
    assert permanent.failure_reason == _reason("VIDEO_UNREADABLE") and permanent_calls == 1
    assert not permanent.HasField("risk_score")


def test_deleting_while_processing_stops_it_and_ends_the_watchers_with_not_found(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        lab.analyzer.gate.clear()
        summary = await _confirm(lab, people.athlete, await _upload(lab, people.athlete, people.profile_id))
        await lab.analyzer.started.wait()
        watching = asyncio.create_task(_watch(lab, people.athlete, summary.id))
        await asyncio.sleep(0.2)
        forbidden = await _failure(
            lab.stub.DeleteAnalysis(analysis_pb2.DeleteAnalysisRequest(analysis_id=summary.id), metadata=bearer(people.coach))
        )
        await lab.stub.DeleteAnalysis(analysis_pb2.DeleteAnalysisRequest(analysis_id=summary.id), metadata=bearer(people.athlete))
        events, error = await watching
        lab.analyzer.gate.set()
        await asyncio.sleep(0.1)
        return forbidden, events, error, await _stored(lab, summary.id), lab.bucket.objects

    forbidden, events, error, stored, objects = _run(tmp_path, scenario)

    # Al coach le dejo ver los análisis de su deportista con cuenta, pero no borrarlos
    assert error_info(forbidden).reason == "FORBIDDEN"
    assert events and error is not None and error.code() is grpc.StatusCode.NOT_FOUND
    assert stored is None and objects == {}


def test_the_startup_recovery_resumes_stalled_analyses_and_closes_the_exhausted_ones(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        old = NOW - timedelta(minutes=10)
        async with lab.world.session_factory() as session:
            rows = [
                JumpAnalysis(athlete_id=people.profile_id, video_reference=lab.bucket.url_for(f"videos/{name}"),
                             movement_type=MovementType.JUMP, attempts=attempts, progress_updated_at=updated)
                for name, attempts, updated in [("stalled", 1, old), ("exhausted", MAX_ATTEMPTS, old), ("alive", 1, NOW)]
            ]
            session.add_all(rows)
            await session.commit()
            ids = [row.id for row in rows]
        resumed = await lab.recovery.recover()
        stalled, _ = await _watch(lab, people.athlete, ids[0])
        exhausted, _ = await _watch(lab, people.athlete, ids[1])
        return resumed, stalled[-1].finished, exhausted[-1].finished, await _stored(lab, ids[2]), len(lab.analyzer.calls)

    resumed, stalled, exhausted, alive, calls = _run(tmp_path, scenario)

    assert resumed == 2 and calls == 1
    assert stalled.status == movement_pb2.ANALYSIS_STATUS_PROCESSED
    assert exhausted.status == movement_pb2.ANALYSIS_STATUS_FAILED and exhausted.failure_reason == _reason("AI_UNAVAILABLE")
    assert alive.status is JumpAnalysisStatus.PENDING


def test_listings_are_paginated_newest_first_and_respect_who_may_see_them(tmp_path: Path) -> None:
    async def scenario(lab: _Lab):
        people = await _people(lab.world)
        async with lab.world.session_factory() as session:
            for index, profile_id in enumerate([people.profile_id, people.managed_id, people.profile_id]):
                session.add(JumpAnalysis(athlete_id=profile_id, video_reference=f"{BUCKET_URL}videos/{index}",
                                         status=JumpAnalysisStatus.FAILED, failure_reason="NO_MOVEMENT_DETECTED"))
            await session.commit()
        coach = bearer(people.coach)
        first = await lab.stub.ListCoachedAnalyses(
            analysis_pb2.ListCoachedAnalysesRequest(page=pagination_pb2.PageRequest(page_size=2)), metadata=coach
        )
        second = await lab.stub.ListCoachedAnalyses(
            analysis_pb2.ListCoachedAnalysesRequest(
                page=pagination_pb2.PageRequest(page_size=2, page_token=first.page.next_page_token)
            ),
            metadata=coach,
        )
        stranger = await _failure(lab.stub.ListAthleteAnalyses(
            analysis_pb2.ListAthleteAnalysesRequest(athlete_id=people.profile_id), metadata=bearer(people.stranger)
        ))
        not_coach = await _failure(lab.stub.ListCoachedAnalyses(analysis_pb2.ListCoachedAnalysesRequest(), metadata=bearer(people.athlete)))
        return first, second, stranger, not_coach

    first, second, stranger, not_coach = _run(tmp_path, scenario)

    assert [a.id for a in first.analyses] == [3, 2] and first.page.next_page_token
    assert [a.id for a in second.analyses] == [1] and second.page.next_page_token == ""
    assert first.analyses[0].failure_reason == _reason("NO_MOVEMENT_DETECTED")
    assert not first.analyses[0].HasField("risk_score")
    assert error_info(stranger).reason == "FORBIDDEN"
    assert not_coach.code() is grpc.StatusCode.PERMISSION_DENIED
