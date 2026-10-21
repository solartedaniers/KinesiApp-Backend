"""Pruebo ManagedAthleteService por la red: CRUD del coach, su foto en el bucket y el borrado en cascada."""

import asyncio
from functools import partial
from pathlib import Path

import grpc
import pytest
from kinesiapp.athlete.v1 import athlete_pb2
from kinesiapp.athlete.v1 import managed_athlete_service_pb2 as managed_pb2
from kinesiapp.athlete.v1 import managed_athlete_service_pb2_grpc as managed_pb2_grpc
from kinesiapp.common.v1 import date_pb2, storage_pb2
from sqlalchemy import func, select

from app.account.inputs import AccountInputRules
from app.athletes.inputs import AthleteInputRules
from app.athletes.managed_athlete_avatars import ManagedAthleteAvatars
from app.athletes.managed_athletes import ManagedAthletes
from app.models.jump_analysis import JointAngleMeasurement, JumpAnalysis
from app.models.team import Team
from app.models.user import UserRole
from app.rpc.athlete_messages import AthleteMessages
from app.rpc.managed_athlete_servicer import ManagedAthleteServicer
from app.storage.avatar_files import AvatarFiles
from app.storage.avatar_links import AvatarLinks
from app.storage.upload_tickets import UploadTicketService
from app.settings.athlete import AthleteSettings
from tests.grpc_harness import error_info, field_violations
from tests.rpc_world import AUTH_SETTINGS, FakeBucket, World, bearer, rpc_world, uow_factory

MAX_AVATAR_BYTES = 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
PRODUCTION_VIDEO = "https://public.example/videos/old.mp4"


def _run(tmp_path: Path, scenario, images: FakeBucket | None = None, videos: FakeBucket | None = None):
    images, videos = images or FakeBucket(), videos or FakeBucket()

    def register(session_factory):
        uows = uow_factory(session_factory)
        files = AvatarFiles(images, UploadTicketService(AUTH_SETTINGS, 60), MAX_AVATAR_BYTES)
        servicer = ManagedAthleteServicer(
            AthleteInputRules.from_settings(AthleteSettings(_env_file=None)),
            AccountInputRules(MAX_AVATAR_BYTES),
            ManagedAthletes(uows, files, videos),
            ManagedAthleteAvatars(uows, files),
            AthleteMessages(AvatarLinks(images)),
        )
        return partial(managed_pb2_grpc.add_ManagedAthleteServiceServicer_to_server, servicer)

    async def main():
        async with rpc_world(tmp_path / "managed.db", register) as world:
            return await scenario(world, managed_pb2_grpc.ManagedAthleteServiceStub(world.channel))

    return asyncio.run(main())


async def _error_of(call) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await call
    return raised.value


def _with_buckets(scenario, *buckets):
    async def bound(world: World, stub):
        return await scenario(world, stub, *buckets)

    return bound


def _create_request(full_name: str = "Juan Pérez") -> managed_pb2.CreateManagedAthleteRequest:
    biometrics = athlete_pb2.Biometrics(
        gender=athlete_pb2.GENDER_MALE,
        height_cm=172.0,
        weight_kg=68.0,
        birth_date=date_pb2.CalendarDate(year=2009, month=8, day=1),
    )
    return managed_pb2.CreateManagedAthleteRequest(full_name=full_name, biometrics=biometrics)


def test_coach_creates_lists_and_edits_their_managed_athletes(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        created = (await stub.CreateManagedAthlete(_create_request(), metadata=bearer(coach))).athlete
        invalid = await _error_of(stub.CreateManagedAthlete(_create_request("R2D2"), metadata=bearer(coach)))
        renamed = await stub.UpdateManagedAthlete(
            managed_pb2.UpdateManagedAthleteRequest(
                athlete_id=created.id, full_name="Juan  Pablo", biometrics=athlete_pb2.BiometricsUpdate(height_cm=175.0)
            ),
            metadata=bearer(coach),
        )
        listed = await stub.ListManagedAthletes(managed_pb2.ListManagedAthletesRequest(), metadata=bearer(coach))
        return coach, created, invalid, renamed.athlete, listed.athletes

    coach, created, invalid, renamed, listed = _run(tmp_path, scenario)

    assert (created.display_name, created.is_managed, created.coach_id) == ("Juan Pérez", True, coach.id)
    assert not created.HasField("user_id")
    assert field_violations(invalid) == ["full_name"]
    assert (renamed.display_name, renamed.biometrics.height_cm, renamed.biometrics.weight_kg) == ("Juan Pablo", 175.0, 68.0)
    assert [athlete.id for athlete in listed] == [created.id]


def test_another_coach_neither_sees_nor_touches_them(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        intruder = await world.user("intruso@kinesiapp.com", UserRole.COACH)
        athlete = await world.user("ana@kinesiapp.com")
        created = (await stub.CreateManagedAthlete(_create_request(), metadata=bearer(coach))).athlete
        listed = await stub.ListManagedAthletes(managed_pb2.ListManagedAthletesRequest(), metadata=bearer(intruder))
        calls = [
            stub.UpdateManagedAthlete(managed_pb2.UpdateManagedAthleteRequest(athlete_id=created.id), metadata=bearer(intruder)),
            stub.DeleteManagedAthlete(managed_pb2.DeleteManagedAthleteRequest(athlete_id=created.id), metadata=bearer(intruder)),
            stub.CreateManagedAthleteAvatarUpload(
                managed_pb2.CreateManagedAthleteAvatarUploadRequest(
                    athlete_id=created.id, content_type=storage_pb2.IMAGE_CONTENT_TYPE_PNG, content_length=len(PNG)
                ),
                metadata=bearer(intruder),
            ),
        ]
        codes = [(await _error_of(call)).code() for call in calls]
        as_athlete = await _error_of(stub.ListManagedAthletes(managed_pb2.ListManagedAthletesRequest(), metadata=bearer(athlete)))
        return list(listed.athletes), codes, as_athlete

    listed, codes, as_athlete = _run(tmp_path, scenario)

    assert listed == []
    assert codes == [grpc.StatusCode.NOT_FOUND] * 3
    assert error_info(as_athlete).reason == "FORBIDDEN"


def test_managed_athlete_avatar_goes_directly_to_the_bucket(tmp_path: Path) -> None:
    async def scenario(world: World, stub, images: FakeBucket):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        first = (await stub.CreateManagedAthlete(_create_request(), metadata=bearer(coach))).athlete
        second = (await stub.CreateManagedAthlete(_create_request("Otro Deportista"), metadata=bearer(coach))).athlete
        upload = await stub.CreateManagedAthleteAvatarUpload(
            managed_pb2.CreateManagedAthleteAvatarUploadRequest(
                athlete_id=first.id, content_type=storage_pb2.IMAGE_CONTENT_TYPE_PNG, content_length=len(PNG)
            ),
            metadata=bearer(coach),
        )
        key = images.signed_uploads[-1][0]
        images.browser_put(key, PNG, "image/png")
        # Compruebo que el ticket de un deportista no sirve para la foto de otro, aunque sea del mismo coach
        swapped = await _error_of(
            stub.ConfirmManagedAthleteAvatarUpload(
                managed_pb2.ConfirmManagedAthleteAvatarUploadRequest(athlete_id=second.id, upload_id=upload.upload_id),
                metadata=bearer(coach),
            )
        )
        confirmed = await stub.ConfirmManagedAthleteAvatarUpload(
            managed_pb2.ConfirmManagedAthleteAvatarUploadRequest(athlete_id=first.id, upload_id=upload.upload_id),
            metadata=bearer(coach),
        )
        with_avatar = dict(images.objects)
        removed = await stub.DeleteManagedAthleteAvatar(
            managed_pb2.DeleteManagedAthleteAvatarRequest(athlete_id=first.id), metadata=bearer(coach)
        )
        return key, swapped, confirmed.athlete, with_avatar, removed.athlete, dict(images.objects)

    images = FakeBucket()
    key, swapped, confirmed, with_avatar, removed, after = _run(tmp_path, _with_buckets(scenario, images), images)

    assert error_info(swapped).reason == "UPLOAD_NOT_FOUND"
    assert confirmed.avatar.url.startswith(f"https://bucket.test/images/{key}?signature=get")
    assert set(with_avatar) == {key}
    assert not removed.HasField("avatar") and after == {}


def test_deleting_a_managed_athlete_removes_analyses_teams_and_files(tmp_path: Path) -> None:
    async def scenario(world: World, stub, images: FakeBucket, videos: FakeBucket):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        created = (await stub.CreateManagedAthlete(_create_request(), metadata=bearer(coach))).athlete
        images.browser_put("avatars/juan.png", PNG, "image/png")
        videos.browser_put("jumps/juan.mp4", b"video", "video/mp4")
        async with world.uow() as uow:
            athlete = await uow.athletes.get(created.id)
            athlete.avatar_url = images.url_for("avatars/juan.png")
            analysis = JumpAnalysis(athlete_id=created.id, video_reference=videos.url_for("jumps/juan.mp4"))
            analysis.angle_measurements.append(
                JointAngleMeasurement(joint_name="knee", angle_degrees=120.0, frame_timestamp_ms=0)
            )
            uow.athletes.add(analysis)
            uow.athletes.add(JumpAnalysis(athlete_id=created.id, video_reference=PRODUCTION_VIDEO))
            team = Team(name="Sub 17", owner_id=coach.id)
            team.athletes.append(athlete)
            uow.teams.add(team)
            await uow.commit()

        await stub.DeleteManagedAthlete(managed_pb2.DeleteManagedAthleteRequest(athlete_id=created.id), metadata=bearer(coach))
        again = await _error_of(
            stub.DeleteManagedAthlete(managed_pb2.DeleteManagedAthleteRequest(athlete_id=created.id), metadata=bearer(coach))
        )
        async with world.session_factory() as session:
            counts = [
                await session.scalar(select(func.count()).select_from(model))
                for model in (JumpAnalysis, JointAngleMeasurement)
            ]
        async with world.uow() as uow:
            members = [team.athlete_ids for team in await uow.teams.list_all()]
        return again, counts, members, dict(images.objects), dict(videos.objects)

    images, videos = FakeBucket(), FakeBucket()
    again, counts, members, image_objects, video_objects = _run(
        tmp_path, _with_buckets(scenario, images, videos), images, videos
    )

    assert again.code() == grpc.StatusCode.NOT_FOUND
    assert counts == [0, 0]
    # Compruebo que el equipo sigue existiendo, solo sin el deportista borrado
    assert members == [[]]
    assert image_objects == {} and video_objects == {}
