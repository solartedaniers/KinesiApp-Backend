from collections.abc import Callable
from datetime import datetime, timezone
from functools import partial

import grpc
from kinesiapp.account.v1 import account_pb2_grpc
from kinesiapp.auth.v1 import auth_pb2_grpc
from kinesiapp.system.v1 import system_pb2_grpc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.account.account_profile import AccountProfile
from app.account.avatar_management import AvatarManagement
from app.account.inputs import AccountInputRules
from app.account.video_consent import VideoConsent
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
from app.identity.password_policy import PasswordPolicy
from app.mail.auth_email_service import AuthEmailService
from app.mail.sender_factory import build_email_sender
from app.repositories.unit_of_work import UnitOfWork
from app.rpc.account_servicer import AccountServicer
from app.rpc.auth_servicer import AuthServicer
from app.rpc.client_policy import build_client_policy
from app.rpc.system_servicer import SystemServicer
from app.services.email_domain_checker import EmailDomainChecker
from app.settings.athlete import AthleteSettings
from app.settings.auth import AuthSettings, PasswordPolicySettings
from app.settings.chat import ChatSettings
from app.settings.mail import MailSettings
from app.settings.storage import MediaSettings, StorageSettings
from app.storage.avatar_links import AvatarLinks
from app.storage.signed_storage_factory import build_signed_storage
from app.storage.upload_tickets import UploadTicketService

ServicerRegistration = Callable[[grpc.aio.Server], None]


class RpcServiceFactory:
    """Factory: arma cada servicer con sus dependencias a partir de la configuración de su dominio."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], auth_settings: AuthSettings) -> None:
        self._uow_factory = partial(UnitOfWork, session_factory)
        self._auth_settings = auth_settings
        self._media_settings = MediaSettings()
        self._password_policy = PasswordPolicy(PasswordPolicySettings())
        storage = StorageSettings()
        self._images = build_signed_storage(storage, self._media_settings, storage.S3_IMAGES_BUCKET)
        self._avatar_links = AvatarLinks(self._images)

    def registrations(self) -> list[ServicerRegistration]:
        return [
            partial(system_pb2_grpc.add_SystemServiceServicer_to_server, self._system()),
            partial(auth_pb2_grpc.add_AuthServiceServicer_to_server, self._auth()),
            partial(account_pb2_grpc.add_AccountServiceServicer_to_server, self._account()),
        ]

    @staticmethod
    def _clock() -> datetime:
        return datetime.now(timezone.utc)

    def _system(self) -> SystemServicer:
        client_policy = build_client_policy(self._media_settings, self._password_policy, AthleteSettings(), ChatSettings())
        return SystemServicer(self._clock, client_policy, UnavailableAiLifecycle())

    def _auth(self) -> AuthServicer:
        auth = self._auth_settings
        mail = MailSettings()
        hasher = PasswordHasher()
        tokens = SessionTokenService(auth)
        sessions = SessionIssuer(tokens)
        codes = OneTimeCodes(auth, hasher)
        passwords = PasswordReplacer(hasher)
        mailer = ThreadedAuthMailer(AuthEmailService(build_email_sender(mail), auth.OTP_EXPIRE_MINUTES))
        return AuthServicer(
            AuthInputRules(self._password_policy, auth.OTP_LENGTH),
            Registration(
                self._uow_factory,
                hasher,
                codes,
                mailer,
                EmailDomainChecker(mail.EMAIL_DNS_TIMEOUT_SECONDS),
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
