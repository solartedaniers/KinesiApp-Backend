from collections.abc import Callable
from datetime import datetime, timezone
from functools import partial

import grpc
from kinesiapp.account.v1 import account_pb2_grpc
from kinesiapp.admin.v1 import user_admin_pb2_grpc
from kinesiapp.auth.v1 import auth_pb2_grpc
from kinesiapp.system.v1 import system_pb2_grpc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.account.account_profile import AccountProfile
from app.account.avatar_management import AvatarManagement
from app.account.inputs import AccountInputRules
from app.account.video_consent import VideoConsent
from app.admin.inputs import AdminInputRules
from app.admin.user_activation import UserActivation
from app.admin.user_directory import UserDirectory
from app.admin.user_provisioning import UserProvisioning
from app.admin.user_role_assignment import UserRoleAssignment
from app.ai.lifecycle import UnavailableAiLifecycle
from app.auth.auth_mailer import ThreadedAuthMailer
from app.auth.email_verification import EmailVerification
from app.auth.inputs import AuthInputRules
from app.auth.one_time_codes import OneTimeCodes
from app.auth.password_change import PasswordChange
from app.auth.password_hasher import PasswordHasher
from app.auth.password_recovery import PasswordRecovery
from app.auth.password_replacer import PasswordReplacer
from app.auth.registration import Registration
from app.auth.session_issuer import SessionIssuer
from app.auth.session_management import SessionManagement
from app.auth.session_tokens import SessionTokenService
from app.core.pagination import PageRules
from app.identity.password_policy import PasswordPolicy
from app.mail.auth_email_service import AuthEmailService
from app.mail.sender_factory import build_email_sender
from app.repositories.unit_of_work import UnitOfWork
from app.rpc.account_servicer import AccountServicer
from app.rpc.auth_servicer import AuthServicer
from app.rpc.client_policy import build_client_policy
from app.rpc.system_servicer import SystemServicer
from app.rpc.user_admin_servicer import UserAdminServicer
from app.services.email_domain_checker import EmailDomainChecker
from app.settings.athlete import AthleteSettings
from app.settings.auth import AuthSettings, PasswordPolicySettings
from app.settings.chat import ChatSettings
from app.settings.mail import MailSettings
from app.settings.pagination import PaginationSettings
from app.settings.storage import MediaSettings, StorageSettings
from app.storage.avatar_links import AvatarLinks
from app.storage.signed_storage_factory import build_signed_storage
from app.storage.upload_tickets import UploadTicketService

ServicerRegistration = Callable[[grpc.aio.Server], None]


class RpcServiceFactory:
    """Factory: armo cada servicer con sus dependencias a partir de la configuración de su dominio."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], auth_settings: AuthSettings) -> None:
        self._uow_factory = partial(UnitOfWork, session_factory)
        self._auth_settings = auth_settings
        self._media_settings = MediaSettings()
        self._password_policy = PasswordPolicy(PasswordPolicySettings())
        self._mail_settings = MailSettings()
        # Comparto el hasher, los códigos y el correo entre auth y admin: los dos emiten códigos de verificación
        self._hasher = PasswordHasher()
        self._codes = OneTimeCodes(auth_settings, self._hasher)
        self._mailer = ThreadedAuthMailer(
            AuthEmailService(build_email_sender(self._mail_settings), auth_settings.OTP_EXPIRE_MINUTES)
        )
        storage = StorageSettings()
        self._images = build_signed_storage(storage, self._media_settings, storage.S3_PRIVATE_IMAGES_BUCKET)
        self._avatar_links = AvatarLinks(self._images)

    def registrations(self) -> list[ServicerRegistration]:
        return [
            partial(system_pb2_grpc.add_SystemServiceServicer_to_server, self._system()),
            partial(auth_pb2_grpc.add_AuthServiceServicer_to_server, self._auth()),
            partial(account_pb2_grpc.add_AccountServiceServicer_to_server, self._account()),
            partial(user_admin_pb2_grpc.add_UserAdminServiceServicer_to_server, self._user_admin()),
        ]

    @staticmethod
    def _clock() -> datetime:
        return datetime.now(timezone.utc)

    def _system(self) -> SystemServicer:
        client_policy = build_client_policy(self._media_settings, self._password_policy, AthleteSettings(), ChatSettings())
        return SystemServicer(self._clock, client_policy, UnavailableAiLifecycle())

    def _auth(self) -> AuthServicer:
        hasher, codes, mailer = self._hasher, self._codes, self._mailer
        tokens = SessionTokenService(self._auth_settings)
        sessions = SessionIssuer(tokens)
        passwords = PasswordReplacer(hasher)
        return AuthServicer(
            AuthInputRules(self._password_policy, self._auth_settings.OTP_LENGTH),
            Registration(
                self._uow_factory,
                hasher,
                codes,
                mailer,
                EmailDomainChecker(self._mail_settings.EMAIL_DNS_TIMEOUT_SECONDS),
                self._media_settings.VIDEO_CONSENT_VERSION,
            ),
            EmailVerification(self._uow_factory, codes, mailer, sessions),
            SessionManagement(self._uow_factory, hasher, tokens, sessions),
            PasswordRecovery(self._uow_factory, codes, mailer, passwords),
            PasswordChange(self._uow_factory, hasher, passwords, sessions),
        )

    def _account(self) -> AccountServicer:
        media = self._media_settings
        tickets = UploadTicketService(self._auth_settings, media.UPLOAD_TICKET_EXPIRE_SECONDS)
        return AccountServicer(
            AccountInputRules(media.MAX_AVATAR_UPLOAD_BYTES),
            AccountProfile(self._uow_factory),
            AvatarManagement(self._uow_factory, self._images, tickets, media.MAX_AVATAR_UPLOAD_BYTES),
            VideoConsent(self._uow_factory, media.VIDEO_CONSENT_VERSION),
            self._avatar_links,
        )

    def _user_admin(self) -> UserAdminServicer:
        return UserAdminServicer(
            AdminInputRules(self._password_policy),
            PageRules.from_settings(PaginationSettings()),
            UserProvisioning(self._uow_factory, self._hasher, self._codes, self._mailer),
            UserDirectory(self._uow_factory),
            UserRoleAssignment(self._uow_factory),
            UserActivation(self._uow_factory),
            self._avatar_links,
        )
