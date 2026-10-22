import grpc
from kinesiapp.team.v1 import team_pb2, team_pb2_grpc

from app.account.inputs import AccountInputRules, AvatarUploadInput
from app.identity.principal import current_principal
from app.models.team import Team
from app.rpc.proto_values import image_format_from_proto, signed_url, timestamp, upload_target
from app.storage.avatar_links import AvatarLinks
from app.teams.inputs import TeamIdInput, TeamMemberInput, TeamNameInput, TeamRenameInput
from app.teams.team_catalog import TeamCatalog
from app.teams.team_logos import TeamLogos
from app.teams.team_membership import TeamMembership


class TeamServicer(team_pb2_grpc.TeamServiceServicer):
    """Implemento kinesiapp.team.v1.TeamService; el contrato ya lo restringe a COACH y ADMIN."""

    def __init__(
        self,
        catalog: TeamCatalog,
        membership: TeamMembership,
        logos: TeamLogos,
        logo_rules: AccountInputRules,
        links: AvatarLinks,
    ) -> None:
        self._catalog = catalog
        self._membership = membership
        self._logos = logos
        self._logo_rules = logo_rules
        self._links = links

    async def ListTeams(
        self, request: team_pb2.ListTeamsRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.ListTeamsResponse:
        teams = await self._catalog.list(current_principal())
        return team_pb2.ListTeamsResponse(teams=[self._team(team) for team in teams])

    async def CreateTeam(
        self, request: team_pb2.CreateTeamRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.CreateTeamResponse:
        data = TeamNameInput.model_validate({"name": request.name})
        return team_pb2.CreateTeamResponse(team=self._team(await self._catalog.create(current_principal(), data.name)))

    async def GetTeam(self, request: team_pb2.GetTeamRequest, context: grpc.aio.ServicerContext) -> team_pb2.GetTeamResponse:
        data = TeamIdInput.model_validate({"team_id": request.team_id})
        return team_pb2.GetTeamResponse(team=self._team(await self._catalog.get(current_principal(), data.team_id)))

    async def RenameTeam(
        self, request: team_pb2.RenameTeamRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.RenameTeamResponse:
        data = TeamRenameInput.model_validate({"team_id": request.team_id, "name": request.name})
        team = await self._catalog.rename(current_principal(), data.team_id, data.name)
        return team_pb2.RenameTeamResponse(team=self._team(team))

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
        return team_pb2.AddTeamMemberResponse(team=self._team(team))

    async def RemoveTeamMember(
        self, request: team_pb2.RemoveTeamMemberRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.RemoveTeamMemberResponse:
        data = TeamMemberInput.model_validate({"team_id": request.team_id, "athlete_id": request.athlete_id})
        team = await self._membership.remove(current_principal(), data.team_id, data.athlete_id)
        return team_pb2.RemoveTeamMemberResponse(team=self._team(team))

    async def CreateTeamLogoUpload(
        self, request: team_pb2.CreateTeamLogoUploadRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.CreateTeamLogoUploadResponse:
        team = TeamIdInput.model_validate({"team_id": request.team_id})
        data = self._logo_rules.parse(
            AvatarUploadInput,
            {"image_format": image_format_from_proto(request.content_type), "content_length": request.content_length},
        )
        upload = await self._logos.create_upload(current_principal(), team.team_id, data.image_format, data.content_length)
        return team_pb2.CreateTeamLogoUploadResponse(upload_id=upload.upload_id, target=upload_target(upload.target))

    async def ConfirmTeamLogoUpload(
        self, request: team_pb2.ConfirmTeamLogoUploadRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.ConfirmTeamLogoUploadResponse:
        data = TeamIdInput.model_validate({"team_id": request.team_id})
        team = await self._logos.confirm_upload(current_principal(), data.team_id, request.upload_id)
        return team_pb2.ConfirmTeamLogoUploadResponse(team=self._team(team))

    async def DeleteTeamLogo(
        self, request: team_pb2.DeleteTeamLogoRequest, context: grpc.aio.ServicerContext
    ) -> team_pb2.DeleteTeamLogoResponse:
        data = TeamIdInput.model_validate({"team_id": request.team_id})
        return team_pb2.DeleteTeamLogoResponse(team=self._team(await self._logos.delete(current_principal(), data.team_id)))

    def _team(self, team: Team) -> team_pb2.Team:
        message = team_pb2.Team(
            id=team.id,
            name=team.name,
            owner_id=team.owner_id,
            athlete_ids=team.athlete_ids,
            created_at=timestamp(team.created_at),
        )
        logo = self._links.link(team.logo_url)
        if logo is not None:
            message.logo.CopyFrom(signed_url(logo))
        return message
