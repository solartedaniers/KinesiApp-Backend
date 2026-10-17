import grpc
from kinesiapp.team.v1 import team_pb2, team_pb2_grpc

from app.identity.principal import current_principal
from app.models.team import Team
from app.rpc.proto_values import timestamp
from app.teams.inputs import TeamIdInput, TeamMemberInput, TeamNameInput, TeamRenameInput
from app.teams.team_catalog import TeamCatalog
from app.teams.team_membership import TeamMembership


class TeamServicer(team_pb2_grpc.TeamServiceServicer):
    """Implemento kinesiapp.team.v1.TeamService; el contrato ya lo restringe a COACH y ADMIN."""

    def __init__(self, catalog: TeamCatalog, membership: TeamMembership) -> None:
        self._catalog = catalog
        self._membership = membership

    async def ListTeams(
        self, request: team_pb2.ListTeamsRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.ListTeamsResponse:
        teams = await self._catalog.list(current_principal())
        return team_pb2.ListTeamsResponse(teams=[_team(team) for team in teams])

    async def CreateTeam(
        self, request: team_pb2.CreateTeamRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.CreateTeamResponse:
        data = TeamNameInput.model_validate({"name": request.name})
        return team_pb2.CreateTeamResponse(team=_team(await self._catalog.create(current_principal(), data.name)))

    async def GetTeam(self, request: team_pb2.GetTeamRequest, context: grpc.aio.ServicerContext) -> team_pb2.GetTeamResponse:
        data = TeamIdInput.model_validate({"team_id": request.team_id})
        return team_pb2.GetTeamResponse(team=_team(await self._catalog.get(current_principal(), data.team_id)))

    async def RenameTeam(
        self, request: team_pb2.RenameTeamRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.RenameTeamResponse:
        data = TeamRenameInput.model_validate({"team_id": request.team_id, "name": request.name})
        team = await self._catalog.rename(current_principal(), data.team_id, data.name)
        return team_pb2.RenameTeamResponse(team=_team(team))

    async def DeleteTeam(
        self, request: team_pb2.DeleteTeamRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.DeleteTeamResponse:
        data = TeamIdInput.model_validate({"team_id": request.team_id})
        await self._catalog.delete(current_principal(), data.team_id)
        return team_pb2.DeleteTeamResponse()

    async def AddTeamMember(
        self, request: team_pb2.AddTeamMemberRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.AddTeamMemberResponse:
        data = TeamMemberInput.model_validate({"team_id": request.team_id, "athlete_id": request.athlete_id})
        team = await self._membership.add(current_principal(), data.team_id, data.athlete_id)
        return team_pb2.AddTeamMemberResponse(team=_team(team))

    async def RemoveTeamMember(
        self, request: team_pb2.RemoveTeamMemberRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.RemoveTeamMemberResponse:
        data = TeamMemberInput.model_validate({"team_id": request.team_id, "athlete_id": request.athlete_id})
        team = await self._membership.remove(current_principal(), data.team_id, data.athlete_id)
        return team_pb2.RemoveTeamMemberResponse(team=_team(team))


def _team(team: Team) -> team_pb2.Team:
    return team_pb2.Team(
        id=team.id,
        name=team.name,
        owner_id=team.owner_id,
        athlete_ids=team.athlete_ids,
        created_at=timestamp(team.created_at),
    )
