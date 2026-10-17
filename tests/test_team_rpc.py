"""Pruebo TeamService por la red, con los interceptores reales y SQLite asíncrono."""

import asyncio
from datetime import date
from functools import partial
from pathlib import Path

import grpc
import pytest
from kinesiapp.team.v1 import team_pb2, team_pb2_grpc

from app.models.athlete import AthleteProfile, Gender
from app.models.user import UserRole
from app.rpc.team_servicer import TeamServicer
from app.teams.team_catalog import TeamCatalog
from app.teams.team_membership import TeamMembership
from tests.grpc_harness import error_info, field_violations
from tests.rpc_world import World, bearer, rpc_world, uow_factory


def _run(tmp_path: Path, scenario):
    def register(session_factory):
        uows = uow_factory(session_factory)
        return partial(team_pb2_grpc.add_TeamServiceServicer_to_server, TeamServicer(TeamCatalog(uows), TeamMembership(uows)))

    async def main():
        async with rpc_world(tmp_path / "teams.db", register) as world:
            return await scenario(world, team_pb2_grpc.TeamServiceStub(world.channel))

    return asyncio.run(main())


async def _error_of(call) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await call
    return raised.value


async def _athlete(world: World, coach_id: int | None, full_name: str = "Gestionado Uno") -> AthleteProfile:
    async with world.session_factory() as session:
        athlete = AthleteProfile(
            full_name=full_name, coach_id=coach_id, gender=Gender.MALE, height_cm=180, weight_kg=75, birth_date=date(2001, 2, 3)
        )
        session.add(athlete)
        await session.commit()
        return athlete


def test_coach_creates_renames_and_deletes_teams_with_unique_names(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        other = await world.user("otro@kinesiapp.com", UserRole.COACH)
        created = (await stub.CreateTeam(team_pb2.CreateTeamRequest(name="  Sub 17 "), metadata=bearer(coach))).team
        duplicate = await _error_of(stub.CreateTeam(team_pb2.CreateTeamRequest(name="Sub 17"), metadata=bearer(coach)))
        # El nombre es único por dueño: otro coach puede usar el mismo
        await stub.CreateTeam(team_pb2.CreateTeamRequest(name="Sub 17"), metadata=bearer(other))
        blank = await _error_of(stub.CreateTeam(team_pb2.CreateTeamRequest(name="   "), metadata=bearer(coach)))
        await stub.CreateTeam(team_pb2.CreateTeamRequest(name="Arqueros"), metadata=bearer(coach))
        clash = await _error_of(
            stub.RenameTeam(team_pb2.RenameTeamRequest(team_id=created.id, name="Arqueros"), metadata=bearer(coach))
        )
        renamed = await stub.RenameTeam(team_pb2.RenameTeamRequest(team_id=created.id, name="Sub 18"), metadata=bearer(coach))
        listed = await stub.ListTeams(team_pb2.ListTeamsRequest(), metadata=bearer(coach))
        await stub.DeleteTeam(team_pb2.DeleteTeamRequest(team_id=created.id), metadata=bearer(coach))
        gone = await _error_of(stub.GetTeam(team_pb2.GetTeamRequest(team_id=created.id), metadata=bearer(coach)))
        return coach, created, duplicate, blank, clash, renamed.team, listed.teams, gone

    coach, created, duplicate, blank, clash, renamed, listed, gone = _run(tmp_path, scenario)

    assert (created.name, created.owner_id, list(created.athlete_ids)) == ("Sub 17", coach.id, [])
    assert created.HasField("created_at")
    assert error_info(duplicate).reason == error_info(clash).reason == "TEAM_NAME_TAKEN"
    assert field_violations(blank) == ["name"]
    assert renamed.name == "Sub 18"
    assert [team.name for team in listed] == ["Arqueros", "Sub 18"]
    assert gone.code() == grpc.StatusCode.NOT_FOUND


def test_teams_of_other_coaches_are_invisible_but_the_admin_sees_all(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        intruder = await world.user("intruso@kinesiapp.com", UserRole.COACH)
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        athlete = await world.user("ana@kinesiapp.com")
        team = (await stub.CreateTeam(team_pb2.CreateTeamRequest(name="Sub 17"), metadata=bearer(coach))).team
        await stub.CreateTeam(team_pb2.CreateTeamRequest(name="Admin"), metadata=bearer(admin))
        hidden = [
            (await _error_of(call)).code()
            for call in (
                stub.GetTeam(team_pb2.GetTeamRequest(team_id=team.id), metadata=bearer(intruder)),
                stub.RenameTeam(team_pb2.RenameTeamRequest(team_id=team.id, name="Mío"), metadata=bearer(intruder)),
                stub.DeleteTeam(team_pb2.DeleteTeamRequest(team_id=team.id), metadata=bearer(intruder)),
            )
        ]
        admin_view = await stub.ListTeams(team_pb2.ListTeamsRequest(), metadata=bearer(admin))
        admin_rename = await stub.RenameTeam(team_pb2.RenameTeamRequest(team_id=team.id, name="Sub 18"), metadata=bearer(admin))
        as_athlete = await _error_of(stub.ListTeams(team_pb2.ListTeamsRequest(), metadata=bearer(athlete)))
        return hidden, [t.name for t in admin_view.teams], admin_rename.team, as_athlete

    hidden, admin_names, admin_rename, as_athlete = _run(tmp_path, scenario)

    assert hidden == [grpc.StatusCode.NOT_FOUND] * 3
    assert admin_names == ["Admin", "Sub 17"]
    assert admin_rename.name == "Sub 18"
    assert error_info(as_athlete).reason == "FORBIDDEN"


def test_only_the_owner_coach_athletes_join_a_coach_team_and_membership_is_idempotent(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        other = await world.user("otro@kinesiapp.com", UserRole.COACH)
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        mine = await _athlete(world, coach.id)
        foreign = await _athlete(world, other.id, "Ajeno Uno")
        coach_team = (await stub.CreateTeam(team_pb2.CreateTeamRequest(name="Sub 17"), metadata=bearer(coach))).team
        admin_team = (await stub.CreateTeam(team_pb2.CreateTeamRequest(name="Todos"), metadata=bearer(admin))).team

        def add(caller, team_id, athlete_id):
            request = team_pb2.AddTeamMemberRequest(team_id=team_id, athlete_id=athlete_id)
            return stub.AddTeamMember(request, metadata=bearer(caller))

        def remove(caller, team_id, athlete_id):
            request = team_pb2.RemoveTeamMemberRequest(team_id=team_id, athlete_id=athlete_id)
            return stub.RemoveTeamMember(request, metadata=bearer(caller))

        await add(coach, coach_team.id, mine.id)
        twice = (await add(coach, coach_team.id, mine.id)).team
        foreign_error = await _error_of(add(coach, coach_team.id, foreign.id))
        # Aunque edite un admin, en el equipo de un coach mando la regla del dueño
        admin_on_coach_team = await _error_of(add(admin, coach_team.id, foreign.id))
        admin_team_now = (await add(admin, admin_team.id, foreign.id)).team
        missing = await _error_of(add(coach, coach_team.id, 999))
        removed = (await remove(coach, coach_team.id, mine.id)).team
        removed_again = (await remove(coach, coach_team.id, mine.id)).team
        return mine, foreign, twice, foreign_error, admin_on_coach_team, admin_team_now, missing, removed, removed_again

    mine, foreign, twice, foreign_error, admin_on_coach_team, admin_team_now, missing, removed, removed_again = _run(
        tmp_path, scenario
    )

    assert list(twice.athlete_ids) == [mine.id]
    assert error_info(foreign_error).reason == error_info(admin_on_coach_team).reason == "INVALID_TEAM_MEMBER"
    assert list(admin_team_now.athlete_ids) == [foreign.id]
    assert missing.code() == grpc.StatusCode.NOT_FOUND
    assert list(removed.athlete_ids) == list(removed_again.athlete_ids) == []


def test_simultaneous_creations_with_the_same_name_leave_a_single_team(tmp_path: Path) -> None:
    async def scenario(world: World, stub):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        request = team_pb2.CreateTeamRequest(name="Sub 17")
        outcomes = await asyncio.gather(
            *(stub.CreateTeam(request, metadata=bearer(coach)) for _ in range(5)), return_exceptions=True
        )
        listed = await stub.ListTeams(team_pb2.ListTeamsRequest(), metadata=bearer(coach))
        return outcomes, len(listed.teams)

    outcomes, teams = _run(tmp_path, scenario)

    assert sorted("ok" if isinstance(o, team_pb2.CreateTeamResponse) else error_info(o).reason for o in outcomes) == [
        *["TEAM_NAME_TAKEN"] * 4,
        "ok",
    ]
    assert teams == 1
