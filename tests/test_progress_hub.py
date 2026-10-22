"""Pruebo el Observer del progreso: cada suscriptor recibe lo último, el fin cierra y nada queda colgado."""

import asyncio

from app.analysis.progress import AnalysisFinished, AnalysisProgressUpdate
from app.analysis.progress_hub import AnalysisProgressHub
from app.models.jump_analysis import AnalysisStage

POSE = AnalysisProgressUpdate(AnalysisStage.EXTRACTING_POSE, 10, 40)
LATER = AnalysisProgressUpdate(AnalysisStage.EXTRACTING_POSE, 30, 40)


def test_a_slow_watcher_gets_the_latest_progress_and_then_the_end() -> None:
    async def main():
        hub = AnalysisProgressHub()
        with hub.subscribe(1) as first, hub.subscribe(1) as second, hub.subscribe(2) as other:
            for event in (POSE, LATER, AnalysisFinished(1)):
                hub.publish(1, event)
                await asyncio.sleep(0)
            # El primero no alcanzó a leer: solo ve el fin. El de otro análisis no recibe nada
            seen_first = [event async for event in first.events()]
            hub.publish(1, LATER)
            seen_second = [event async for event in second.events()]
            return seen_first, seen_second, other._latest

    seen_first, seen_second, other_latest = asyncio.run(main())

    assert seen_first == seen_second == [AnalysisFinished(1)]
    assert other_latest is None


def test_a_watcher_reading_along_sees_each_step_and_unsubscribing_cleans_up() -> None:
    async def main():
        hub = AnalysisProgressHub()
        seen = []

        async def watch():
            with hub.subscribe(1) as subscription:
                async for event in subscription.events():
                    seen.append(event)

        watcher = asyncio.create_task(watch())
        await asyncio.sleep(0)
        for event in (POSE, LATER, AnalysisFinished(1)):
            hub.publish(1, event)
            await asyncio.sleep(0)
        await watcher
        return seen, dict(hub._subscriptions)

    seen, left = asyncio.run(main())

    assert seen == [POSE, LATER, AnalysisFinished(1)]
    assert left == {}
