from collections.abc import Callable
from datetime import datetime, timezone
from functools import partial

import grpc
from kinesiapp.account.v1 import account_pb2_grpc
from kinesiapp.analysis.v1 import analysis_pb2_grpc
from kinesiapp.admin.v1 import user_admin_pb2_grpc
from kinesiapp.athlete.v1 import athlete_profile_service_pb2_grpc, managed_athlete_service_pb2_grpc
from kinesiapp.auth.v1 import auth_pb2_grpc
from kinesiapp.chat.v1 import chat_pb2_grpc
from kinesiapp.system.v1 import system_pb2_grpc
from kinesiapp.team.v1 import team_pb2_grpc
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
from app.ai.remote_assistant import RemoteAnalysisAssistant
from app.ai.remote_lifecycle import RemoteAiLifecycle
from app.ai.remote_movement_analyzer import RemoteMovementAnalyzer
from app.ai.transport_factory import build_ai_transport
from app.ai.warming_movement_analyzer import WarmingMovementAnalyzer
from app.analysis.analysis_catalog import AnalysisCatalog
from app.analysis.analysis_processing import AnalysisProcessing
from app.analysis.analysis_recovery import StalledAnalysisRecovery
from app.analysis.analysis_removal import AnalysisRemoval
from app.analysis.analysis_runner import AnalysisRunner
from app.analysis.analysis_watch import AnalysisWatch
from app.analysis.inputs import VideoUploadRules
from app.analysis.progress_hub import AnalysisProgressHub
from app.analysis.retry_policy import RetryPolicy
from app.analysis.knee_reading import KneeReadingExtractor
from app.analysis.risk_assessment_codec import RiskAssessmentCodec
from app.analysis.risk_level import RiskLevelClassifier
from app.analysis.video_playback import VideoPlayback
from app.analysis.video_uploads import VideoUploads
from app.athletes.athlete_administration import AthleteAdministration
from app.athletes.athlete_directory import AthleteDirectory
from app.athletes.inputs import AthleteInputRules
from app.athletes.managed_athlete_avatars import ManagedAthleteAvatars
from app.athletes.managed_athletes import ManagedAthletes
from app.athletes.own_athlete_profile import OwnAthleteProfile
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
from app.chat.analysis_facts import AnalysisFactsBuilder
from app.chat.conversation_history import ConversationHistory
from app.chat.conversation_opening import ConversationOpening
from app.chat.inputs import ChatInputRules
from app.chat.question_answering import QuestionAnswering
from app.chat.usage_limits import ChatUsageLimits
from app.core.pagination import PageRules
from app.identity.password_policy import PasswordPolicy
from app.mail.auth_email_service import AuthEmailService
from app.mail.sender_factory import build_email_sender
from app.repositories.unit_of_work import UnitOfWork
from app.rpc.account_servicer import AccountServicer
from app.rpc.analysis_messages import AnalysisMessages
from app.rpc.analysis_servicer import AnalysisServicer
from app.rpc.athlete_messages import AthleteMessages
from app.rpc.athlete_profile_servicer import AthleteProfileServicer
from app.rpc.auth_servicer import AuthServicer
from app.rpc.chat_servicer import ChatServicer
from app.rpc.client_policy import build_client_policy
from app.rpc.managed_athlete_servicer import ManagedAthleteServicer
from app.rpc.system_servicer import SystemServicer
from app.rpc.team_servicer import TeamServicer
from app.rpc.user_admin_servicer import UserAdminServicer
from app.services.email_domain_checker import EmailDomainChecker
from app.settings.ai import AiClientSettings
from app.settings.analysis import AnalysisSettings, ensure_lease_outlasts_ai_call
from app.settings.athlete import AthleteSettings
from app.settings.auth import AuthSettings, PasswordPolicySettings
from app.settings.chat import ChatSettings
from app.settings.mail import MailSettings
from app.settings.pagination import PaginationSettings
from app.settings.risk import RiskSettings
from app.settings.storage import MediaSettings, StorageSettings
from app.storage.avatar_files import AvatarFiles
from app.storage.avatar_links import AvatarLinks
from app.storage.signed_storage_factory import build_signed_storage
from app.storage.upload_tickets import UploadTicketService
from app.teams.team_catalog import TeamCatalog
from app.teams.team_membership import TeamMembership

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
        self._videos = build_signed_storage(storage, self._media_settings, storage.S3_PRIVATE_VIDEOS_BUCKET)
        self._avatar_links = AvatarLinks(self._images)
        self._tickets = UploadTicketService(auth_settings, self._media_settings.UPLOAD_TICKET_EXPIRE_SECONDS)
        self._avatar_files = AvatarFiles(self._images, self._tickets, self._media_settings.MAX_AVATAR_UPLOAD_BYTES)
        self._athlete_settings = AthleteSettings()
        self._page_rules = PageRules.from_settings(PaginationSettings())
        self._ai_settings = AiClientSettings()
        self._ai = build_ai_transport(self._ai_settings)
        self._chat_settings = ChatSettings()
        risk = RiskSettings()
        self._risk_levels = RiskLevelClassifier(risk.RISK_LEVEL_MODERATE, risk.RISK_LEVEL_HIGH)
        self._risk_codec = RiskAssessmentCodec()
        # Comparto el hub y el runner entre la subida, el seguimiento, el borrado y la recuperación del arranque
        self._analysis_settings = AnalysisSettings()
        ensure_lease_outlasts_ai_call(self._analysis_settings, self._ai_settings)
        self._progress_hub = AnalysisProgressHub()
        self._analysis_runner = AnalysisRunner(self._analysis_processing().process, self._analysis_settings.MAX_CONCURRENCY)

    def registrations(self) -> list[ServicerRegistration]:
        return [
            partial(system_pb2_grpc.add_SystemServiceServicer_to_server, self._system()),
            partial(auth_pb2_grpc.add_AuthServiceServicer_to_server, self._auth()),
            partial(account_pb2_grpc.add_AccountServiceServicer_to_server, self._account()),
            partial(user_admin_pb2_grpc.add_UserAdminServiceServicer_to_server, self._user_admin()),
            partial(athlete_profile_service_pb2_grpc.add_AthleteProfileServiceServicer_to_server, self._athlete_profiles()),
            partial(managed_athlete_service_pb2_grpc.add_ManagedAthleteServiceServicer_to_server, self._managed_athletes()),
            partial(team_pb2_grpc.add_TeamServiceServicer_to_server, self._teams()),
            partial(chat_pb2_grpc.add_ChatServiceServicer_to_server, self._chat()),
            partial(analysis_pb2_grpc.add_AnalysisServiceServicer_to_server, self._analysis()),
        ]

    async def watch_stalled_analyses(self) -> None:
        settings = self._analysis_settings
        recovery = StalledAnalysisRecovery(
            self._uow_factory, self._analysis_runner, settings.PROCESSING_LEASE_SECONDS, self._clock
        )
        await recovery.watch(settings.RECOVERY_INTERVAL_SECONDS)

    async def aclose(self) -> None:
        # Detengo los análisis antes de cerrar el canal que usan hacia la IA
        await self._analysis_runner.aclose()
        await self._ai.aclose()

    @staticmethod
    def _clock() -> datetime:
        return datetime.now(timezone.utc)

    def _ai_lifecycle(self) -> RemoteAiLifecycle:
        ai = self._ai_settings
        return RemoteAiLifecycle(
            self._ai, ai.WAKE_UP_TIMEOUT_SECONDS, ai.WAKE_UP_CALL_TIMEOUT_SECONDS, ai.WAKE_UP_RETRY_INTERVAL_SECONDS
        )

    def _system(self) -> SystemServicer:
        client_policy = build_client_policy(self._media_settings, self._password_policy, self._athlete_settings, self._chat_settings)
        return SystemServicer(self._clock, client_policy, self._ai_lifecycle())

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
        return AccountServicer(
            AccountInputRules(media.MAX_AVATAR_UPLOAD_BYTES),
            AccountProfile(self._uow_factory),
            AvatarManagement(self._uow_factory, self._avatar_files),
            VideoConsent(self._uow_factory, media.VIDEO_CONSENT_VERSION),
            self._avatar_links,
        )

    def _user_admin(self) -> UserAdminServicer:
        return UserAdminServicer(
            AdminInputRules(self._password_policy),
            self._page_rules,
            UserProvisioning(self._uow_factory, self._hasher, self._codes, self._mailer),
            UserDirectory(self._uow_factory),
            UserRoleAssignment(self._uow_factory),
            UserActivation(self._uow_factory),
            self._avatar_links,
        )

    def _athlete_profiles(self) -> AthleteProfileServicer:
        return AthleteProfileServicer(
            AthleteInputRules.from_settings(self._athlete_settings),
            self._page_rules,
            OwnAthleteProfile(self._uow_factory),
            AthleteDirectory(self._uow_factory),
            AthleteAdministration(self._uow_factory),
            AthleteMessages(self._avatar_links),
        )

    def _managed_athletes(self) -> ManagedAthleteServicer:
        return ManagedAthleteServicer(
            AthleteInputRules.from_settings(self._athlete_settings),
            AccountInputRules(self._media_settings.MAX_AVATAR_UPLOAD_BYTES),
            ManagedAthletes(self._uow_factory, self._avatar_files, self._videos),
            ManagedAthleteAvatars(self._uow_factory, self._avatar_files),
            AthleteMessages(self._avatar_links),
        )

    def _teams(self) -> TeamServicer:
        return TeamServicer(TeamCatalog(self._uow_factory), TeamMembership(self._uow_factory))

    def _chat(self) -> ChatServicer:
        chat = self._chat_settings
        facts = AnalysisFactsBuilder(self._risk_codec, self._risk_levels)
        assistant = RemoteAnalysisAssistant(self._ai, self._ai_settings.ASSISTANT_TIMEOUT_SECONDS)
        limits = ChatUsageLimits(chat.CHAT_RATE_LIMIT_PER_USER_PER_HOUR, chat.CHAT_RATE_LIMIT_GLOBAL_PER_MINUTE, self._clock)
        return ChatServicer(
            ChatInputRules(chat.CHAT_MESSAGE_MAX_CHARS),
            ConversationHistory(self._uow_factory),
            ConversationOpening(self._uow_factory, facts, assistant, limits),
            QuestionAnswering(self._uow_factory, facts, assistant, limits),
        )

    def _analysis_processing(self) -> AnalysisProcessing:
        settings = self._analysis_settings
        return AnalysisProcessing(
            self._uow_factory,
            self._videos,
            WarmingMovementAnalyzer(self._ai_lifecycle(), RemoteMovementAnalyzer(self._ai, settings.STREAM_TIMEOUT_SECONDS)),
            self._progress_hub,
            self._risk_codec,
            RetryPolicy.from_settings(settings),
            settings.PROGRESS_PERSIST_INTERVAL_SECONDS,
            settings.PROCESSING_LEASE_SECONDS,
            self._clock,
        )

    def _analysis(self) -> AnalysisServicer:
        media = self._media_settings
        rules = VideoUploadRules(media.MAX_VIDEO_UPLOAD_BYTES, media.MAX_VIDEO_DURATION_SECONDS * 1000)
        runner, hub = self._analysis_runner, self._progress_hub
        return AnalysisServicer(
            self._page_rules,
            VideoUploads(self._uow_factory, self._videos, self._tickets, rules, media.VIDEO_CONSENT_VERSION, runner),
            AnalysisWatch(self._uow_factory, hub),
            AnalysisCatalog(self._uow_factory),
            AnalysisRemoval(self._uow_factory, self._videos, runner, hub),
            VideoPlayback(self._uow_factory, self._videos),
            AnalysisMessages(self._risk_codec, self._risk_levels, KneeReadingExtractor()),
        )
