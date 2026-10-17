import grpc
from kinesiapp.athlete.v1 import athlete_profile_service_pb2 as profiles_pb2
from kinesiapp.athlete.v1 import athlete_profile_service_pb2_grpc as profiles_pb2_grpc
from kinesiapp.common.v1 import pagination_pb2

from app.athletes.athlete_administration import AthleteAdministration
from app.athletes.athlete_directory import AthleteDirectory
from app.athletes.inputs import (
    AthleteIdInput,
    AthleteInputRules,
    BiometricsInput,
    BiometricsUpdateInput,
    CoachAssignmentInput,
    ProfileForUserInput,
)
from app.athletes.own_athlete_profile import OwnAthleteProfile
from app.core.pagination import PageRules, encode_page_token
from app.identity.principal import current_principal
from app.rpc.athlete_messages import AthleteMessages, biometrics_fields, biometrics_update_fields


class AthleteProfileServicer(profiles_pb2_grpc.AthleteProfileServiceServicer):
    """Implemento kinesiapp.athlete.v1.AthleteProfileService: las fichas de deportistas con cuenta propia."""

    def __init__(
        self,
        rules: AthleteInputRules,
        pages: PageRules,
        own_profile: OwnAthleteProfile,
        directory: AthleteDirectory,
        administration: AthleteAdministration,
        messages: AthleteMessages,
    ) -> None:
        self._rules = rules
        self._pages = pages
        self._own_profile = own_profile
        self._directory = directory
        self._administration = administration
        self._messages = messages

    async def CreateMyAthleteProfile(
        self, request: profiles_pb2.CreateMyAthleteProfileRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.CreateMyAthleteProfileResponse:
        biometrics = self._rules.parse(BiometricsInput, biometrics_fields(request.biometrics))
        athlete = await self._own_profile.create(current_principal().user_id, biometrics)
        return profiles_pb2.CreateMyAthleteProfileResponse(athlete=self._messages.profile(athlete))

    async def GetMyAthleteProfile(
        self, request: profiles_pb2.GetMyAthleteProfileRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.GetMyAthleteProfileResponse:
        athlete = await self._own_profile.get(current_principal().user_id)
        return profiles_pb2.GetMyAthleteProfileResponse(athlete=self._messages.profile(athlete))

    async def UpdateMyAthleteProfile(
        self, request: profiles_pb2.UpdateMyAthleteProfileRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.UpdateMyAthleteProfileResponse:
        biometrics = self._rules.parse(BiometricsUpdateInput, biometrics_update_fields(request.biometrics))
        athlete = await self._own_profile.update(current_principal().user_id, biometrics)
        return profiles_pb2.UpdateMyAthleteProfileResponse(athlete=self._messages.profile(athlete))

    async def ListCoachedAthletes(
        self, request: profiles_pb2.ListCoachedAthletesRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.ListCoachedAthletesResponse:
        athletes = await self._directory.list_coached(current_principal().user_id)
        return profiles_pb2.ListCoachedAthletesResponse(athletes=[self._messages.profile(a) for a in athletes])

    async def ListAthletes(
        self, request: profiles_pb2.ListAthletesRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.ListAthletesResponse:
        page = self._pages.parse(request.page.page_size, request.page.page_token)
        result = await self._directory.list(page.after_id, page.limit)
        next_token = encode_page_token(result.last_id) if result.last_id is not None else ""
        return profiles_pb2.ListAthletesResponse(
            athletes=[self._messages.profile(a) for a in result.athletes],
            page=pagination_pb2.PageResponse(next_page_token=next_token),
        )

    async def CreateAthleteProfile(
        self, request: profiles_pb2.CreateAthleteProfileRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.CreateAthleteProfileResponse:
        data = self._rules.parse(
            ProfileForUserInput, {"user_id": request.user_id, "biometrics": biometrics_fields(request.biometrics)}
        )
        athlete = await self._administration.create_for_user(data.user_id, data.biometrics)
        return profiles_pb2.CreateAthleteProfileResponse(athlete=self._messages.profile(athlete))

    async def GetAthleteProfile(
        self, request: profiles_pb2.GetAthleteProfileRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.GetAthleteProfileResponse:
        data = self._rules.parse(AthleteIdInput, {"athlete_id": request.athlete_id})
        athlete = await self._directory.get_visible(current_principal(), data.athlete_id)
        return profiles_pb2.GetAthleteProfileResponse(athlete=self._messages.profile(athlete))

    async def AssignCoach(
        self, request: profiles_pb2.AssignCoachRequest, context: grpc.aio.ServicerContext
    ) -> profiles_pb2.AssignCoachResponse:
        data = self._rules.parse(CoachAssignmentInput, {"athlete_id": request.athlete_id, "coach_id": request.coach_id})
        athlete = await self._administration.assign_coach(data.athlete_id, data.coach_id)
        return profiles_pb2.AssignCoachResponse(athlete=self._messages.profile(athlete))
