"""Medicion de tiempos por frame y de RSS pico del proceso."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import psutil


@dataclass
class TimingStats:
    mean_ms: float
    p95_ms: float
    total_sec: float
    fps: float


class FrameTimer:
    """Acumula duraciones por frame (segundos) y calcula estadisticos."""

    def __init__(self) -> None:
        self._samples: list[float] = []

    def record(self, seconds: float) -> None:
        self._samples.append(seconds)

    def stats(self) -> TimingStats:
        if not self._samples:
            return TimingStats(0.0, 0.0, 0.0, 0.0)
        arr = np.array(self._samples)
        total = float(arr.sum())
        return TimingStats(
            mean_ms=float(arr.mean() * 1000),
            p95_ms=float(np.percentile(arr, 95) * 1000),
            total_sec=total,
            fps=len(arr) / total if total > 0 else 0.0,
        )


@dataclass
class RssSampler:
    """Muestrea la memoria RSS del proceso actual y guarda el pico observado.

    ponytail: sampleo sincrono (una lectura por frame procesado), no un hilo de
    fondo. Es suficiente para comparar variantes de modelo/resolucion en un
    spike; si se necesita el pico exacto entre frames, agregar un hilo de
    muestreo periodico.
    """

    _process: psutil.Process = field(default_factory=lambda: psutil.Process())
    _peak_rss_bytes: int = 0

    def sample(self) -> None:
        rss = self._process.memory_info().rss
        if rss > self._peak_rss_bytes:
            self._peak_rss_bytes = rss

    @property
    def peak_mb(self) -> float:
        return self._peak_rss_bytes / (1024 * 1024)
