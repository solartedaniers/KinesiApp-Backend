import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class AnalysisRunner:
    """Corro cada análisis como una tarea de asyncio del mismo proceso, de a max_concurrency a la vez.

    No espero a que termine: ConfirmVideoUpload responde enseguida. Si el proceso se reinicia, las tareas
    se pierden y los análisis quedan PENDING; los retoma la recuperación del arranque.
    """

    def __init__(self, process: Callable[[int], Awaitable[None]], max_concurrency: int) -> None:
        self._process = process
        self._slots = asyncio.Semaphore(max_concurrency)
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def submit(self, analysis_id: int) -> None:
        # Si ya está en curso no lanzo otro: dos tareas sobre el mismo análisis pelearían por el resultado
        if analysis_id in self._tasks:
            return
        task = asyncio.create_task(self._run(analysis_id), name=f"analysis-{analysis_id}")
        self._tasks[analysis_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(analysis_id, None))

    def cancel(self, analysis_id: int) -> None:
        task = self._tasks.get(analysis_id)
        if task is not None:
            task.cancel()

    async def aclose(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, analysis_id: int) -> None:
        async with self._slots:
            try:
                await self._process(analysis_id)
            except Exception:
                # Lo dejo PENDING: si fue algo pasajero, la recuperación del próximo arranque lo retoma
                logger.exception("Analysis %s crashed", analysis_id)
