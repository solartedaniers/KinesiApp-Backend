import grpc
from kinesiapp.athlete.v1 import managed_athlete_service_pb2 as managed_pb2
from kinesiapp.athlete.v1 import managed_athlete_service_pb2_grpc as managed_pb2_grpc

from app.account.inputs import AccountInputRules, AvatarUploadInput
from app.athletes.inputs import AthleteIdInput, AthleteInputRules, ManagedAthleteInput, ManagedAthleteUpdateInput
from app.athletes.managed_athlete_avatars import ManagedAthleteAvatars
from app.athletes.managed_athletes import ManagedAthletes
from app.identity.principal import current_principal
from app.rpc.athlete_messages import AthleteMessages, biometrics_fields, biometrics_update_fields
from app.rpc.proto_values import image_format_from_proto, upload_target


class ManagedAthleteServicer(managed_pb2_grpc.ManagedAthleteServiceServicer):
    """Implemento kinesiapp.athlete.v1.ManagedAthleteService; el contrato ya restringe cada RPC al rol COACH."""

    def __init__(
        self,
        rules: AthleteInputRules,
        avatar_rules: AccountInputRules,
        athletes: ManagedAthletes,
        avatars: ManagedAthleteAvatars,
        messages: AthleteMessages,
    ) -> None:
        self._rules = rules
        self._avatar_rules = avatar_rules
        self._athletes = athletes
        self._avatars = avatars
        self._messages = messages

    async def ListManagedAthletes(
        self, request: managed_pb2.ListManagedAthletesRequest, context: grpc.aio.ServicerContext
    ) -> managed_pb2.ListManagedAthletesResponse:
        athletes = await self._athletes.list(current_principal().user_id)
        return managed_pb2.ListManagedAthletesResponse(athletes=[self._messages.profile(a) for a in athletes])

    async def CreateManagedAthlete(
        self, request: managed_pb2.CreateManagedAthleteRequest, context: grpc.aio.ServicerContext
    ) -> managed_pb2.CreateManagedAthleteResponse:
        data = self._rules.parse(
            ManagedAthleteInput, {"full_name": request.full_name, "biometrics": biometrics_fields(request.biometrics)}
        )
        athlete = await self._athletes.create(current_principal().user_id, data)
        return managed_pb2.CreateManagedAthleteResponse(athlete=self._messages.profile(athlete))

    async def UpdateManagedAthlete(
        self, request: managed_pb2.UpdateManagedAthleteRequest, context: grpc.aio.ServicerContext
    ) -> managed_pb2.UpdateManagedAthleteResponse:
        fields = {"athlete_id": request.athlete_id, "biometrics": biometrics_update_fields(request.biometrics)}
        if request.HasField("full_name"):
            fields["full_name"] = request.full_name
        athlete = await self._athletes.update(current_principal().user_id, self._rules.parse(ManagedAthleteUpdateInput, fields))
        return managed_pb2.UpdateManagedAthleteResponse(athlete=self._messages.profile(athlete))

    async def DeleteManagedAthlete(
        self, request: managed_pb2.DeleteManagedAthleteRequest, context: grpc.aio.ServicerContext
    ) -> managed_pb2.DeleteManagedAthleteResponse:
        data = self._rules.parse(AthleteIdInput, {"athlete_id": request.athlete_id})
        await self._athletes.delete(current_principal().user_id, data.athlete_id)
        return managed_pb2.DeleteManagedAthleteResponse()

    async def CreateManagedAthleteAvatarUpload(
        self, request: managed_pb2.CreateManagedAthleteAvatarUploadRequest, context: grpc.aio.ServicerContext
    ) -> managed_pb2.CreateManagedAthleteAvatarUploadResponse:
        athlete = self._rules.parse(AthleteIdInput, {"athlete_id": request.athlete_id})
        data = self._avatar_rules.parse(
            AvatarUploadInput,
            {"image_format": image_format_from_proto(request.content_type), "content_length": request.content_length},
        )
        upload = await self._avatars.create_upload(
            current_principal().user_id, athlete.athlete_id, data.image_format, data.content_length
        )
        return managed_pb2.CreateManagedAthleteAvatarUploadResponse(
            upload_id=upload.upload_id, target=upload_target(upload.target)
        )

    async def ConfirmManagedAthleteAvatarUpload(
        self, request: managed_pb2.ConfirmManagedAthleteAvatarUploadRequest, context: grpc.aio.ServicerContext
    ) -> managed_pb2.ConfirmManagedAthleteAvatarUploadResponse:
        data = self._rules.parse(AthleteIdInput, {"athlete_id": request.athlete_id})
        athlete = await self._avatars.confirm_upload(current_principal().user_id, data.athlete_id, request.upload_id)
        return managed_pb2.ConfirmManagedAthleteAvatarUploadResponse(athlete=self._messages.profile(athlete))

    async def DeleteManagedAthleteAvatar(
        self, request: managed_pb2.DeleteManagedAthleteAvatarRequest, context: grpc.aio.ServicerContext
    ) -> managed_pb2.DeleteManagedAthleteAvatarResponse:
        data = self._rules.parse(AthleteIdInput, {"athlete_id": request.athlete_id})
        athlete = await self._avatars.delete(current_principal().user_id, data.athlete_id)
        return managed_pb2.DeleteManagedAthleteAvatarResponse(athlete=self._messages.profile(athlete))
