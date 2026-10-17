import grpc
from kinesiapp.account.v1 import account_pb2, account_pb2_grpc

from app.account.account_profile import AccountProfile
from app.account.avatar_management import AvatarManagement
from app.account.inputs import AccountInputRules, AvatarUploadInput, ProfileInput, VideoConsentInput
from app.account.video_consent import VideoConsent
from app.identity.principal import current_principal
from app.models.user import User
from app.rpc.proto_values import image_format_from_proto, signed_url, timestamp, upload_target
from app.rpc.user_roles import role_to_proto
from app.storage.avatar_links import AvatarLinks


class AccountServicer(account_pb2_grpc.AccountServiceServicer):
    """Implemento kinesiapp.account.v1.AccountService: la cuenta de quien llama, sea cual sea su rol."""

    def __init__(
        self,
        rules: AccountInputRules,
        profile: AccountProfile,
        avatars: AvatarManagement,
        consent: VideoConsent,
        avatar_links: AvatarLinks,
    ) -> None:
        self._rules = rules
        self._profile = profile
        self._avatars = avatars
        self._consent = consent
        self._avatar_links = avatar_links

    async def GetMyAccount(
        self, request: account_pb2.GetMyAccountRequest, context: grpc.aio.ServicerContext
    ) -> account_pb2.GetMyAccountResponse:
        user = await self._profile.get(current_principal().user_id)
        return account_pb2.GetMyAccountResponse(account=self._account(user))

    async def UpdateMyProfile(
        self, request: account_pb2.UpdateMyProfileRequest, context: grpc.aio.ServicerContext
    ) -> account_pb2.UpdateMyProfileResponse:
        data = self._rules.parse(ProfileInput, {"full_name": request.full_name})
        user = await self._profile.rename(current_principal().user_id, data.full_name)
        return account_pb2.UpdateMyProfileResponse(account=self._account(user))

    async def CreateAvatarUpload(
        self, request: account_pb2.CreateAvatarUploadRequest, context: grpc.aio.ServicerContext
    ) -> account_pb2.CreateAvatarUploadResponse:
        data = self._rules.parse(
            AvatarUploadInput,
            {"image_format": image_format_from_proto(request.content_type), "content_length": request.content_length},
        )
        upload = self._avatars.create_upload(current_principal().user_id, data.image_format, data.content_length)
        return account_pb2.CreateAvatarUploadResponse(upload_id=upload.upload_id, target=upload_target(upload.target))

    async def ConfirmAvatarUpload(
        self, request: account_pb2.ConfirmAvatarUploadRequest, context: grpc.aio.ServicerContext
    ) -> account_pb2.ConfirmAvatarUploadResponse:
        user = await self._avatars.confirm_upload(current_principal().user_id, request.upload_id)
        return account_pb2.ConfirmAvatarUploadResponse(account=self._account(user))

    async def DeleteMyAvatar(
        self, request: account_pb2.DeleteMyAvatarRequest, context: grpc.aio.ServicerContext
    ) -> account_pb2.DeleteMyAvatarResponse:
        user = await self._avatars.delete(current_principal().user_id)
        return account_pb2.DeleteMyAvatarResponse(account=self._account(user))

    async def GrantVideoConsent(
        self, request: account_pb2.GrantVideoConsentRequest, context: grpc.aio.ServicerContext
    ) -> account_pb2.GrantVideoConsentResponse:
        data = self._rules.parse(VideoConsentInput, {"version": request.version})
        user = await self._consent.grant(current_principal().user_id, data.version)
        return account_pb2.GrantVideoConsentResponse(account=self._account(user))

    def _account(self, user: User) -> account_pb2.Account:
        account = account_pb2.Account(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=role_to_proto(user.role),
            created_at=timestamp(user.created_at),
        )
        avatar = self._avatar_links.link(user.avatar_url)
        if avatar is not None:
            account.avatar.CopyFrom(signed_url(avatar))
        if user.video_consent_version is not None and user.video_consent_given_at is not None:
            account.video_consent_version = user.video_consent_version
            account.video_consent_given_at.CopyFrom(timestamp(user.video_consent_given_at))
        return account
