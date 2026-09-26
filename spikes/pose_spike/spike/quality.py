"""Metricas de calidad de deteccion: % de frames sin pose y distribucion de
visibilidad de cadera/rodilla/tobillo."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class QualityReport:
    total_frames: int
    frames_without_pose: int
    pct_without_pose: float
    visibility_mean: dict
    visibility_p10: dict


def _stats(values: list[float]) -> tuple[float, float]:
    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return 0.0, 0.0
    return float(arr.mean()), float(np.percentile(arr, 10))


def compute_quality(
    detected_flags: list[bool], hip_vis: list[float], knee_vis: list[float], ankle_vis: list[float]
) -> QualityReport:
    total = len(detected_flags)
    missing = total - sum(detected_flags)
    hip_mean, hip_p10 = _stats(hip_vis)
    knee_mean, knee_p10 = _stats(knee_vis)
    ankle_mean, ankle_p10 = _stats(ankle_vis)
    return QualityReport(
        total_frames=total,
        frames_without_pose=missing,
        pct_without_pose=(missing / total * 100) if total else 0.0,
        visibility_mean={"hip": hip_mean, "knee": knee_mean, "ankle": ankle_mean},
        visibility_p10={"hip": hip_p10, "knee": knee_p10, "ankle": ankle_p10},
    )
