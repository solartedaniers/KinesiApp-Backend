from collections.abc import AsyncIterator

import grpc
from kinesiapp.analysis.v1 import analysis_pb2, analysis_pb2_grpc
from kinesiapp.common.v1 import pagination_pb2

from app.analysis.analysis_catalog import AnalysisCatalog, AnalysisPage
from app.analysis.analysis_removal import AnalysisRemoval
from app.analysis.analysis_watch import AnalysisWatch
from app.analysis.inputs import AnalysisIdInput, UploadIdInput, VideoUploadInput
from app.analysis.video_playback import VideoPlayback
from app.analysis.video_uploads import VideoUploads
from app.athletes.inputs import AthleteIdInput
from app.core.pagination import PageRules, encode_page_token
from app.identity.principal import current_principal
from app.models.jump_analysis import JumpAnalysis
from app.rpc.analysis_messages import AnalysisMessages, progress
from app.rpc.proto_values import signed_url, upload_target
from app.teams.inputs import TeamIdInput


class AnalysisServicer(analysis_pb2_grpc.AnalysisServiceServicer):
    """Implemento kinesiapp.analysis.v1.AnalysisService; los permisos por deportista los deciden los casos de uso."""

    def __init__(
        self,
        pages: PageRules,
        uploads: VideoUploads,
        watch: AnalysisWatch,
        catalog: AnalysisCatalog,
        removal: AnalysisRemoval,
        playback: VideoPlayback,
        messages: AnalysisMessages,
    ) -> None:
        self._pages = pages
        self._uploads = uploads
        self._watch = watch
        self._catalog = catalog
        self._removal = removal
        self._playback = playback
        self._messages = messages

    async def CreateVideoUpload(
        self, request: analysis_pb2.CreateVideoUploadRequest, context: grpc.aio.ServicerContext
    ) -> analysis_pb2.CreateVideoUploadResponse:
        data = VideoUploadInput.model_validate(
            {
                "athlete_id": request.athlete_id,
                "movement_type": request.movement_type,
                "content_type": request.content_type,
                "content_length": request.content_length,
                "duration_ms": request.duration_ms,
            }
        )
        upload = await self._uploads.create_upload(current_principal(), data)
        return analysis_pb2.CreateVideoUploadResponse(upload_id=upload.upload_id, target=upload_target(upload.target))

    async def ConfirmVideoUpload(
        self, request: analysis_pb2.ConfirmVideoUploadRequest, context: grpc.aio.ServicerContext
    ) -> analysis_pb2.ConfirmVideoUploadResponse:
        data = UploadIdInput.model_validate({"upload_id": request.upload_id})
        analysis = await self._uploads.confirm_upload(current_principal(), data.upload_id)
        return analysis_pb2.ConfirmVideoUploadResponse(analysis=self._messages.summary(analysis))

    async def WatchAnalysis(
        self, request: analysis_pb2.WatchAnalysisRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[analysis_pb2.WatchAnalysisResponse]:
        data = AnalysisIdInput.model_validate({"analysis_id": request.analysis_id})
        async for event in self._watch.watch(current_principal(), data.analysis_id):
            if isinstance(event, JumpAnalysis):
                yield analysis_pb2.WatchAnalysisResponse(finished=self._messages.summary(event))
            else:
                yield analysis_pb2.WatchAnalysisResponse(progress=progress(event))

    async def GetAnalysis(
        self, request: analysis_pb2.GetAnalysisRequest, context: grpc.aio.ServicerContext
    ) -> analysis_pb2.GetAnalysisResponse:
        data = AnalysisIdInput.model_validate({"analysis_id": request.analysis_id})
        analysis = await self._catalog.get(current_principal(), data.analysis_id)
        return analysis_pb2.GetAnalysisResponse(analysis=self._messages.detail(analysis))

    async def ListAthleteAnalyses(
        self, request: analysis_pb2.ListAthleteAnalysesRequest, context: grpc.aio.ServicerContext
    ) -> analysis_pb2.ListAthleteAnalysesResponse:
        data = AthleteIdInput.model_validate({"athlete_id": request.athlete_id})
        page = self._pages.parse(request.page.page_size, request.page.page_token)
        result = await self._catalog.list_for_athlete(current_principal(), data.athlete_id, page.after_id, page.limit)
        analyses, next_page = self._page(result)
        return analysis_pb2.ListAthleteAnalysesResponse(analyses=analyses, page=next_page)

    async def ListCoachedAnalyses(
        self, request: analysis_pb2.ListCoachedAnalysesRequest, context: grpc.aio.ServicerContext
    ) -> analysis_pb2.ListCoachedAnalysesResponse:
        page = self._pages.parse(request.page.page_size, request.page.page_token)
        team_id = TeamIdInput.model_validate({"team_id": request.team_id}).team_id if request.HasField("team_id") else None
        result = await self._catalog.list_coached(current_principal(), page.after_id, page.limit, team_id)
        analyses, next_page = self._page(result)
        return analysis_pb2.ListCoachedAnalysesResponse(analyses=analyses, page=next_page)

    async def DeleteAnalysis(
        self, request: analysis_pb2.DeleteAnalysisRequest, context: grpc.aio.ServicerContext
    ) -> analysis_pb2.DeleteAnalysisResponse:
        data = AnalysisIdInput.model_validate({"analysis_id": request.analysis_id})
        await self._removal.delete(current_principal(), data.analysis_id)
        return analysis_pb2.DeleteAnalysisResponse()

    async def GetVideoPlaybackUrl(
        self, request: analysis_pb2.GetVideoPlaybackUrlRequest, context: grpc.aio.ServicerContext
    ) -> analysis_pb2.GetVideoPlaybackUrlResponse:
        data = AnalysisIdInput.model_validate({"analysis_id": request.analysis_id})
        video = await self._playback.link(current_principal(), data.analysis_id)
        return analysis_pb2.GetVideoPlaybackUrlResponse(video=signed_url(video))

    def _page(self, result: AnalysisPage) -> tuple[list[analysis_pb2.AnalysisSummary], pagination_pb2.PageResponse]:
        next_token = encode_page_token(result.last_id) if result.last_id is not None else ""
        summaries = [self._messages.summary(analysis) for analysis in result.analyses]
        return summaries, pagination_pb2.PageResponse(next_page_token=next_token)
