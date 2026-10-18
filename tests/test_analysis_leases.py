"""Pruebo dos instancias del backend sobre la misma base, como en un deploy de Render: la nueva no retoma un
análisis cuya llamada a la IA sigue viva, y un intento que perdió el lease no guarda encima del nuevo dueño."""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  registra todos los modelos en Base.metadata
from app.analysis.analysis_processing import AnalysisProcessing
from app.analysis.analysis_recovery import StalledAnalysisRecovery
from app.analysis.progress import AnalysisProgressUpdate
from app.analysis.progress_hub import AnalysisProgressHub
from app.analysis.retry_policy import RetryPolicy
from app.analysis.risk_assessment_codec import RiskAssessmentCodec
from app.core.async_database import build_session_factory
from app.models.athlete import AthleteProfile, Gender
from app.models.base import Base
from app.models.jump_analysis import AnalysisStage, JointAngleMeasurement, JumpAnalysis, JumpAnalysisStatus, MovementType
from app.models.user import User, UserRole
from tests.rpc_world import FakeBucket, uow_factory
from tests.test_analysis_rpc import _result

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
STREAM_TIMEOUT = 180.0
LEASE = 300.0


@dataclass
class _Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _Analyzer:
    """Simulo la IA de una instancia: avanza una etapa y espera a que la prueba suelte la compuerta."""

    def __init__(self, version: str) -> None:
        self.version = version
        self.calls = 0
        self.gate = asyncio.Event()
        self.started = asyncio.Event()

    async def analyze(self, video_url: str, movement_type: MovementType):
        self.calls += 1
        yield AnalysisProgressUpdate(AnalysisStage.EXTRACTING_POSE, 10, 100)
        self.started.set()
        await self.gate.wait()
        result = _result()
        result.pose_model_version = self.version
        yield result


@dataclass
class _Submissions:
    """Recojo lo que la recuperación manda a correr para lanzarlo yo y poder esperarlo."""

    ids: list[int] = field(default_factory=list)

    def submit(self, analysis_id: int) -> None:
        self.ids.append(analysis_id)


@dataclass
class _Instance:
    analyzer: _Analyzer
    processing: AnalysisProcessing
    recovery: StalledAnalysisRecovery
    submissions: _Submissions

    async def recover(self) -> list[asyncio.Task[None]]:
        await self.recovery.recover()
        return [asyncio.create_task(self.processing.process(analysis_id)) for analysis_id in self.submissions.ids]


def _instance(uows, clock: _Clock, version: str) -> _Instance:
    analyzer, submissions = _Analyzer(version), _Submissions()

    async def sleep(seconds: float) -> None:
        return None

    processing = AnalysisProcessing(
        uows, FakeBucket(), analyzer, AnalysisProgressHub(), RiskAssessmentCodec(), RetryPolicy(3, 5.0, 2.0, 60.0),
        0.0, LEASE, clock, sleep,
    )
    return _Instance(analyzer, processing, StalledAnalysisRecovery(uows, submissions, LEASE, clock), submissions)


def _deploy(tmp_path: Path, scenario):
    async def main():
        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'leases.db').as_posix()}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = build_session_factory(engine)
        uows, clock = uow_factory(session_factory), _Clock()
        try:
            async with session_factory() as session:
                user = User(email="atleta@kinesiapp.com", hashed_password="unused", full_name="Atleta", role=UserRole.ATHLETE)
                session.add(user)
                await session.flush()
                profile = AthleteProfile(user_id=user.id, gender=Gender.FEMALE, height_cm=165, weight_kg=60,
                                         birth_date=date(2002, 5, 6))
                session.add(profile)
                await session.flush()
                analysis = JumpAnalysis(athlete_id=profile.id, video_reference=FakeBucket().url_for("videos/1/v.mp4"),
                                        movement_type=MovementType.SQUAT, progress_updated_at=NOW)
                session.add(analysis)
                await session.commit()
            old, new = _instance(uows, clock, "pose-old"), _instance(uows, clock, "pose-new")
            return await scenario(analysis.id, old, new, clock, session_factory)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _stored(session_factory, analysis_id: int) -> tuple[JumpAnalysis, int]:
    async with session_factory() as session:
        analysis = await session.get(JumpAnalysis, analysis_id)
        samples = await session.scalar(
            select(func.count()).select_from(JointAngleMeasurement).where(JointAngleMeasurement.jump_analysis_id == analysis_id)
        )
        return analysis, samples


def test_the_new_instance_does_not_retake_an_analysis_whose_ai_call_is_still_running(tmp_path: Path) -> None:
    async def scenario(analysis_id, old, new, clock, session_factory):
        running = asyncio.create_task(old.processing.process(analysis_id))
        await old.analyzer.started.wait()
        # La llamada a la IA todavía está dentro de su plazo, aunque lleve un rato sin avanzar
        clock.advance(STREAM_TIMEOUT - 10)
        retaken = await new.recover()
        await asyncio.sleep(0.1)
        old.analyzer.gate.set()
        new.analyzer.gate.set()
        await asyncio.gather(running, *retaken)
        return new.analyzer.calls, await _stored(session_factory, analysis_id)

    new_calls, (stored, samples) = _deploy(tmp_path, scenario)

    assert new_calls == 0
    assert stored.status is JumpAnalysisStatus.PROCESSED and stored.pose_model_version == "pose-old" and samples == 2


def test_an_attempt_that_lost_its_lease_cannot_save_over_the_new_owner(tmp_path: Path) -> None:
    async def scenario(analysis_id, old, new, clock, session_factory):
        running = asyncio.create_task(old.processing.process(analysis_id))
        await old.analyzer.started.wait()
        # La instancia vieja quedó colgada más allá del lease: la nueva lo reclama
        clock.advance(LEASE + 1)
        retaken = await new.recover()
        await new.analyzer.started.wait()
        old.analyzer.gate.set()
        await running
        after_old, _ = await _stored(session_factory, analysis_id)
        new.analyzer.gate.set()
        await asyncio.gather(*retaken)
        return after_old.status, await _stored(session_factory, analysis_id)

    after_old, (stored, samples) = _deploy(tmp_path, scenario)

    assert after_old is JumpAnalysisStatus.PENDING
    assert stored.status is JumpAnalysisStatus.PROCESSED and stored.pose_model_version == "pose-new" and samples == 2
