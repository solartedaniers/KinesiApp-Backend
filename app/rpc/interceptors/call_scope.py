import inspect
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import grpc

UnaryBehavior = Callable[[Any, grpc.aio.ServicerContext], Awaitable[Any] | Any]
StreamBehavior = Callable[[Any, grpc.aio.ServicerContext], AsyncIterator[Any]]


class CallScopeInterceptor(grpc.aio.ServerInterceptor, ABC):
    """Template Method: cada interceptor solo define qué pasa alrededor de una llamada, sea unaria o de stream."""

    @abstractmethod
    def scope(self, method: str, context: grpc.aio.ServicerContext) -> AbstractAsyncContextManager[None]: ...

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler | None]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        handler = await continuation(handler_call_details)
        if handler is None:
            return None
        method = handler_call_details.method
        # Solo envuelvo unario y server streaming: gRPC-Web no soporta los otros y el contrato no los usa
        if handler.unary_unary is not None:
            return handler._replace(unary_unary=self._wrap_unary(method, handler.unary_unary))
        if handler.unary_stream is not None:
            return handler._replace(unary_stream=self._wrap_stream(method, handler.unary_stream))
        return handler

    def _wrap_unary(self, method: str, behavior: UnaryBehavior) -> UnaryBehavior:
        async def wrapped(request: Any, context: grpc.aio.ServicerContext) -> Any:
            async with self.scope(method, context):
                # Los servicers base generados son síncronos (responden UNIMPLEMENTED); los míos, async
                result = behavior(request, context)
                return await result if inspect.isawaitable(result) else result

        return wrapped

    def _wrap_stream(self, method: str, behavior: StreamBehavior) -> StreamBehavior:
        async def wrapped(request: Any, context: grpc.aio.ServicerContext) -> AsyncIterator[Any]:
            async with self.scope(method, context):
                async for response in behavior(request, context):
                    yield response

        return wrapped
