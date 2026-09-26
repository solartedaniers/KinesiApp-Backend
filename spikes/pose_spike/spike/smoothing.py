"""Suavizado de series (media movil) y medida de ruido, con relleno de huecos
por interpolacion lineal para frames sin deteccion (NaN)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def interpolate_gaps(series: np.ndarray) -> np.ndarray:
    arr = series.astype(float).copy()
    nans = np.isnan(arr)
    if not nans.any() or nans.all():
        return arr
    idx = np.arange(len(arr))
    arr[nans] = np.interp(idx[nans], idx[~nans], arr[~nans])
    return arr


def moving_average(series: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return series.copy()
    pad = window // 2
    padded = np.pad(series, pad, mode="edge")
    kernel = np.ones(window) / window
    smoothed = np.convolve(padded, kernel, mode="same")
    return smoothed[pad : pad + len(series)]


def noise_level(series: np.ndarray) -> float:
    """Ruido = desviacion estandar de la diferencia frame a frame."""
    diffs = np.diff(series)
    diffs = diffs[~np.isnan(diffs)]
    return float(np.std(diffs)) if len(diffs) else 0.0


@dataclass
class SmoothingResult:
    interpolated: np.ndarray
    smoothed: np.ndarray
    noise_before: float
    noise_after: float


class LandmarkSeriesPreprocessor:
    """Interpola huecos y aplica media movil a una serie de una sola variable
    (angulo o coordenada) a lo largo de los frames."""

    def __init__(self, window: int = 5) -> None:
        self.window = window

    def process(self, series: np.ndarray) -> SmoothingResult:
        interpolated = interpolate_gaps(series)
        smoothed = moving_average(interpolated, self.window)
        return SmoothingResult(
            interpolated=interpolated,
            smoothed=smoothed,
            noise_before=noise_level(interpolated),
            noise_after=noise_level(smoothed),
        )
