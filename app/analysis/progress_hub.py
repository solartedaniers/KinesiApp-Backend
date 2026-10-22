import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from app.analysis.progress import AnalysisEvent, AnalysisFinished


class ProgressSubscription:
    """Observer de un análisis. Guardo solo el último evento: a quien mira le sirve el avance más reciente,
    y así un cliente lento nunca acumula memoria."""

    def __init__(self) -> None:
        self._latest: AnalysisEvent | None = None
        self._arrived = asyncio.Event()

    def notify(self, event: AnalysisEvent) -> None:
        # Un fin ya avisado no lo pisa un avance que llegue tarde
        if not isinstance(self._latest, AnalysisFinished):
            self._latest = event
            self._arrived.set()

    async def events(self) -> AsyncIterator[AnalysisEvent]:
        while True:
            await self._arrived.wait()
            self._arrived.clear()
            event, self._latest = self._latest, None
            if event is None:
                continue
            yield event
            if isinstance(event, AnalysisFinished):
                return


class AnalysisProgressHub:
    """Subject del patrón Observer: el procesamiento publica y cada WatchAnalysis abierto recibe.

    Vive en memoria del proceso porque el backend corre en una sola instancia; quien llega tarde o tras un
    reinicio lee primero el progreso persistido en la base.
    """

    def __init__(self) -> None:
        self._subscriptions: defaultdict[int, set[ProgressSubscription]] = defaultdict(set)

    @contextmanager
    def subscribe(self, analysis_id: int) -> Iterator[ProgressSubscription]:
        subscription = ProgressSubscription()
        self._subscriptions[analysis_id].add(subscription)
        try:
            yield subscription
        finally:
            subscribers = self._subscriptions[analysis_id]
            subscribers.discard(subscription)
            if not subscribers:
                del self._subscriptions[analysis_id]

    def publish(self, analysis_id: int, event: AnalysisEvent) -> None:
        for subscription in self._subscriptions.get(analysis_id, ()):
            subscription.notify(event)
