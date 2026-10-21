"""Pruebo AthleteProfileService por la red, con los interceptores reales y SQLite asíncrono."""

import asyncio
from datetime import date
from functools import partial
from pathlib import Path

import grpc
import pytest
from kinesiapp.athlete.v1 import athlete_pb2
from kinesiapp.athlete.v1 import athlete_profile_service_pb2 as profiles_pb2
from kinesiapp.athlete.v1 import athlete_profile_service_pb2_grpc as profiles_pb2_grpc
from kinesiapp.common.v1 import date_pb2, pagination_pb2

from app.athletes.athlete_administration import AthleteAdministration
from app.athletes.athlete_directory import AthleteDirectory
from app.athletes.inputs import AthleteInputRules
from app.athletes.own_athlete_profile import OwnAthleteProfile
from app.core.pagination import PageRules
from app.models.athlete import AthleteProfile, Gender
from app.models.team import Team
from app.models.user import UserRole
from app.settings.athlete import AthleteSettings
from app.rpc.athlete_messages import AthleteMessages
from app.rpc.athlete_profile_servicer import AthleteProfileServicer
from app.storage.avatar_links import AvatarLinks
from tests.grpc_harness import error_info, field_violations
from tests.rpc_world import FakeBucket, World, bearer, rpc_world, uow_factory

RULES = AthleteInputRules.from_settings(AthleteSettings(_env_file=None))


def _run(tmp_path: Path, scenario):
    def register(session_factory):
        uows = uow_factory(session_factory)
        servicer = AthleteProfileServicer(
            RULES,
            PageRules(default_size=2, max_size=3),
            OwnAthleteProfile(uows),
            AthleteDirectory(uows),
            AthleteAdministration(uows),
            AthleteMessages(AvatarLinks(FakeBucket())),
        )
        return partial(profiles_pb2_grpc.add_AthleteProfileServiceServicer_to_server, servicer)

    async def main():
        async with rpc_world(tmp_path / "athletes.db", register) as world:
            return await scenario(world, profiles_pb2_grpc.AthleteProfileServiceStub(world.channel))

    return asyncio.run(main())


async def _error_of(call) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await call
    return raised.value


def _biometrics(**overrides) -> athlete_pb2.Biometrics:
    fields = {
        "gender": athlete_pb2.GENDER_FEMALE,
        "height_cm": 168.0,
        "weight_kg": 61.5,
        "birth_date": date_pb2.CalendarDate(year=2004, month=5, day=17),
    }
    return athlete_pb2.Biometrics(**{**fields, **overrides})


async def _profile(world: World, **fields) -> AthleteProfile:
    async with world.session_factory() as session:
        athlete = AthleteProfile(gender=Gender.MALE, height_cm=180, weight_kg=75, birth_date=date(2001, 2, 3), **fields)
        session.add(athlete)
        await session.commit()
        return athlete


def test_onboarding_creates_reads_and_edits_my_profile(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        ana = await world.user("ana@kinesiapp.com")
        missing = await _error_of(stub.GetMyAthleteProfile(profiles_pb2.GetMyAthleteProfileRequest(), metadata=bearer(ana)))
        created = await stub.CreateMyAthleteProfile(
            profiles_pb2.CreateMyAthleteProfileRequest(biometrics=_biometrics()), metadata=bearer(ana)
        )
        twice = await _error_of(
            stub.CreateMyAthleteProfile(profiles_pb2.CreateMyAthleteProfileRequest(biometrics=_biometrics()), metadata=bearer(ana))
        )
        update = athlete_pb2.BiometricsUpdate(weight_kg=63.0)
        updated = await stub.UpdateMyAthleteProfile(
            profiles_pb2.UpdateMyAthleteProfileRequest(biometrics=update), metadata=bearer(ana)
        )
        mine = await stub.GetMyAthleteProfile(profiles_pb2.GetMyAthleteProfileRequest(), metadata=bearer(ana))
        return ana, missing, created.athlete, twice, updated.athlete, mine.athlete

    ana, missing, created, twice, updated, mine = _run(tmp_path, scenario)

    assert missing.code() == grpc.StatusCode.NOT_FOUND
    assert (created.user_id, created.display_name, created.is_managed) == (ana.id, "Persona Prueba", False)
    assert created.biometrics.birth_date == date_pb2.CalendarDate(year=2004, month=5, day=17)
    assert not created.HasField("coach_id") and not created.HasField("avatar")
    assert (twice.code(), error_info(twice).reason) == (grpc.StatusCode.ALREADY_EXISTS, "PROFILE_ALREADY_EXISTS")
    # Compruebo que la edición parcial solo cambia el peso
    assert (updated.biometrics.weight_kg, updated.biometrics.height_cm) == (63.0, 168.0)
    assert mine == updated


def test_invalid_biometrics_report_every_field(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        ana = await world.user("ana@kinesiapp.com")
        bad = _biometrics(
            gender=athlete_pb2.GENDER_UNSPECIFIED,
            height_cm=0,
            weight_kg=401,
            birth_date=date_pb2.CalendarDate(year=2099, month=1, day=1),
        )
        invalid = await _error_of(
            stub.CreateMyAthleteProfile(profiles_pb2.CreateMyAthleteProfileRequest(biometrics=bad), metadata=bearer(ana))
        )
        impossible_day = await _error_of(
            stub.UpdateMyAthleteProfile(
                profiles_pb2.UpdateMyAthleteProfileRequest(
                    biometrics=athlete_pb2.BiometricsUpdate(birth_date=date_pb2.CalendarDate(year=2004, month=2, day=31))
                ),
                metadata=bearer(ana),
            )
        )
        return invalid, impossible_day

    invalid, impossible_day = _run(tmp_path, scenario)

    assert invalid.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert sorted(field_violations(invalid)) == ["birth_date", "gender", "height_cm", "weight_kg"]
    assert field_violations(impossible_day) == ["birth_date"]


def test_height_in_meters_or_weight_in_pounds_are_rejected(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        ana = await world.user("ana@kinesiapp.com")
        meters = await _error_of(
            stub.CreateMyAthleteProfile(
                profiles_pb2.CreateMyAthleteProfileRequest(biometrics=_biometrics(height_cm=1.75)), metadata=bearer(ana)
            )
        )
        await stub.CreateMyAthleteProfile(profiles_pb2.CreateMyAthleteProfileRequest(biometrics=_biometrics()), metadata=bearer(ana))
        pounds = await _error_of(
            stub.UpdateMyAthleteProfile(
                profiles_pb2.UpdateMyAthleteProfileRequest(biometrics=athlete_pb2.BiometricsUpdate(weight_kg=300)),
                metadata=bearer(ana),
            )
        )
        edges = await stub.UpdateMyAthleteProfile(
            profiles_pb2.UpdateMyAthleteProfileRequest(
                biometrics=athlete_pb2.BiometricsUpdate(height_cm=RULES.min_height_cm, weight_kg=RULES.max_weight_kg)
            ),
            metadata=bearer(ana),
        )
        return meters, pounds, edges

    meters, pounds, edges = _run(tmp_path, scenario)

    assert meters.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert field_violations(meters) == ["height_cm"]
    assert field_violations(pounds) == ["weight_kg"]
    # Los extremos del rango son válidos
    assert (edges.athlete.biometrics.height_cm, edges.athlete.biometrics.weight_kg) == (RULES.min_height_cm, RULES.max_weight_kg)


def test_only_athletes_have_their_own_profile(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        return await _error_of(
            stub.CreateMyAthleteProfile(profiles_pb2.CreateMyAthleteProfileRequest(biometrics=_biometrics()), metadata=bearer(coach))
        )

    assert error_info(_run(tmp_path, scenario)).reason == "FORBIDDEN"


def test_a_profile_is_visible_to_its_athlete_their_coach_and_the_admin(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        other_coach = await world.user("otro.coach@kinesiapp.com", UserRole.COACH)
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        ana = await world.user("ana@kinesiapp.com")
        luis = await world.user("luis@kinesiapp.com")
        profile = await _profile(world, user_id=ana.id, coach_id=coach.id)

        def get(caller, athlete_id=profile.id):
            return stub.GetAthleteProfile(profiles_pb2.GetAthleteProfileRequest(athlete_id=athlete_id), metadata=bearer(caller))

        seen = [(await get(caller)).athlete.coach_name for caller in (ana, coach, admin)]
        denied = [error_info(await _error_of(get(caller))).reason for caller in (luis, other_coach)]
        missing = await _error_of(get(admin, 999))
        return seen, denied, missing

    seen, denied, missing = _run(tmp_path, scenario)

    assert seen == ["Persona Prueba"] * 3
    assert denied == ["FORBIDDEN", "FORBIDDEN"]
    assert missing.code() == grpc.StatusCode.NOT_FOUND


def test_admin_creates_profiles_only_for_athlete_accounts(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        ana = await world.user("ana@kinesiapp.com")
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)

        def create(user_id):
            request = profiles_pb2.CreateAthleteProfileRequest(user_id=user_id, biometrics=_biometrics())
            return stub.CreateAthleteProfile(request, metadata=bearer(admin))

        created = await create(ana.id)
        for_coach = await _error_of(create(coach.id))
        unknown = await _error_of(create(999))
        as_athlete = await _error_of(
            stub.CreateAthleteProfile(profiles_pb2.CreateAthleteProfileRequest(user_id=ana.id), metadata=bearer(ana))
        )
        return ana, created.athlete, for_coach, unknown, as_athlete

    ana, created, for_coach, unknown, as_athlete = _run(tmp_path, scenario)

    assert created.user_id == ana.id
    assert error_info(for_coach).reason == "INVALID_ROLE_ASSIGNMENT"
    assert unknown.code() == grpc.StatusCode.NOT_FOUND
    assert error_info(as_athlete).reason == "FORBIDDEN"


def test_assigning_a_coach_moves_the_athlete_out_of_the_previous_coach_teams(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        old_coach = await world.user("viejo@kinesiapp.com", UserRole.COACH)
        new_coach = await world.user("nuevo@kinesiapp.com", UserRole.COACH)
        ana = await world.user("ana@kinesiapp.com")
        profile = await _profile(world, user_id=ana.id, coach_id=old_coach.id)
        managed = await _profile(world, full_name="Gestionado Uno", coach_id=new_coach.id)
        async with world.session_factory() as session:
            session.add_all([Team(name="Sub 17", owner_id=old_coach.id), Team(name="Todos", owner_id=admin.id)])
            await session.commit()
        async with world.uow() as uow:
            for team in await uow.teams.list_all():
                team.athletes.append(await uow.athletes.get(profile.id))
            await uow.commit()

        def assign(coach_id):
            request = profiles_pb2.AssignCoachRequest(athlete_id=profile.id, coach_id=coach_id)
            return stub.AssignCoach(request, metadata=bearer(admin))

        not_a_coach = await _error_of(assign(ana.id))
        assigned = await assign(new_coach.id)
        coached = await stub.ListCoachedAthletes(profiles_pb2.ListCoachedAthletesRequest(), metadata=bearer(new_coach))
        async with world.uow() as uow:
            teams = {team.name: team.athlete_ids for team in await uow.teams.list_all()}
        return profile, managed, not_a_coach, assigned.athlete, coached.athletes, teams

    profile, managed, not_a_coach, assigned, coached, teams = _run(tmp_path, scenario)

    assert error_info(not_a_coach).reason == "INVALID_ROLE_ASSIGNMENT"
    assert assigned.coach_name == "Persona Prueba"
    # Compruebo que el listado del coach no mezcla a sus deportistas gestionados
    assert [athlete.id for athlete in coached] == [profile.id]
    assert teams == {"Sub 17": [], "Todos": [profile.id]}


def test_admin_lists_every_athlete_by_pages(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        for index in range(3):
            account = await world.user(f"deportista{index}@kinesiapp.com")
            await _profile(world, user_id=account.id)
        await _profile(world, full_name="Gestionado Uno", coach_id=coach.id)
        pages, token = [], ""
        while True:
            request = profiles_pb2.ListAthletesRequest(page=pagination_pb2.PageRequest(page_token=token))
            response = await stub.ListAthletes(request, metadata=bearer(admin))
            pages.append([athlete.display_name for athlete in response.athletes])
            token = response.page.next_page_token
            if not token:
                return pages

    assert _run(tmp_path, scenario) == [["Persona Prueba"] * 2, ["Persona Prueba", "Gestionado Uno"]]


def test_simultaneous_onboardings_leave_a_single_profile(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        ana = await world.user("ana@kinesiapp.com")
        request = profiles_pb2.CreateMyAthleteProfileRequest(biometrics=_biometrics())
        outcomes = await asyncio.gather(
            *(stub.CreateMyAthleteProfile(request, metadata=bearer(ana)) for _ in range(5)), return_exceptions=True
        )
        return sorted(
            "ok" if isinstance(o, profiles_pb2.CreateMyAthleteProfileResponse) else error_info(o).reason for o in outcomes
        )

    assert _run(tmp_path, scenario) == [*["PROFILE_ALREADY_EXISTS"] * 4, "ok"]
