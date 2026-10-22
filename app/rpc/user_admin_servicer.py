import grpc
from kinesiapp.admin.v1 import user_admin_pb2, user_admin_pb2_grpc
from kinesiapp.common.v1 import pagination_pb2

from app.admin.inputs import AdminInputRules, NewUserInput, RoleChangeInput, StatusChangeInput, UserIdInput
from app.admin.user_activation import UserActivation
from app.admin.user_directory import UserDirectory
from app.admin.user_provisioning import UserProvisioning
from app.admin.user_role_assignment import UserRoleAssignment
from app.core.pagination import PageRules, encode_page_token
from app.identity.principal import current_principal
from app.models.user import User
from app.rpc.proto_values import signed_url, timestamp
from app.rpc.user_roles import role_from_proto, role_to_proto
from app.storage.avatar_links import AvatarLinks


class UserAdminServicer(user_admin_pb2_grpc.UserAdminServiceServicer):
    """Implemento kinesiapp.admin.v1.UserAdminService; el contrato ya restringe cada RPC al rol ADMIN."""

    def __init__(
        self,
        rules: AdminInputRules,
        pages: PageRules,
        provisioning: UserProvisioning,
        directory: UserDirectory,
        roles: UserRoleAssignment,
        activation: UserActivation,
        avatar_links: AvatarLinks,
    ) -> None:
        self._rules = rules
        self._pages = pages
        self._provisioning = provisioning
        self._directory = directory
        self._roles = roles
        self._activation = activation
        self._avatar_links = avatar_links

    async def CreateUser(
        self, request: user_admin_pb2.CreateUserRequest, context: grpc.aio.ServicerContext
    ) -> user_admin_pb2.CreateUserResponse:
        data = self._rules.parse(
            NewUserInput,
            {
                "email": request.email,
                "password": request.password,
                "full_name": request.full_name,
                "role": role_from_proto(request.role),
            },
        )
        return user_admin_pb2.CreateUserResponse(user=self._user(await self._provisioning.create(data)))

    async def GetUser(
        self, request: user_admin_pb2.GetUserRequest, context: grpc.aio.ServicerContext
    ) -> user_admin_pb2.GetUserResponse:
        data = self._rules.parse(UserIdInput, {"user_id": request.user_id})
        return user_admin_pb2.GetUserResponse(user=self._user(await self._directory.get(data.user_id)))

    async def ListUsers(
        self, request: user_admin_pb2.ListUsersRequest, context: grpc.aio.ServicerContext
    ) -> user_admin_pb2.ListUsersResponse:
        page = self._pages.parse(request.page.page_size, request.page.page_token)
        result = await self._directory.list(page.after_id, page.limit)
        next_token = encode_page_token(result.last_id) if result.last_id is not None else ""
        return user_admin_pb2.ListUsersResponse(
            users=[self._user(user) for user in result.users],
            page=pagination_pb2.PageResponse(next_page_token=next_token),
        )

    async def UpdateUserRole(
        self, request: user_admin_pb2.UpdateUserRoleRequest, context: grpc.aio.ServicerContext
    ) -> user_admin_pb2.UpdateUserRoleResponse:
        data = self._rules.parse(RoleChangeInput, {"user_id": request.user_id, "role": role_from_proto(request.role)})
        user = await self._roles.assign(current_principal().user_id, data.user_id, data.role)
        return user_admin_pb2.UpdateUserRoleResponse(user=self._user(user))

    async def UpdateUserStatus(
        self, request: user_admin_pb2.UpdateUserStatusRequest, context: grpc.aio.ServicerContext
    ) -> user_admin_pb2.UpdateUserStatusResponse:
        data = self._rules.parse(StatusChangeInput, {"user_id": request.user_id, "is_active": request.is_active})
        user = await self._activation.set_active(current_principal().user_id, data.user_id, data.is_active)
        return user_admin_pb2.UpdateUserStatusResponse(user=self._user(user))

    def _user(self, user: User) -> user_admin_pb2.User:
        message = user_admin_pb2.User(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=role_to_proto(user.role),
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=timestamp(user.created_at),
        )
        avatar = self._avatar_links.link(user.avatar_url)
        if avatar is not None:
            message.avatar.CopyFrom(signed_url(avatar))
        return message
