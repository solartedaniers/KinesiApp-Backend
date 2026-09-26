"""Deteccion de despegue/apice/aterrizaje a partir de la trayectoria vertical
de la cadera (y normalizada; recordar que en coordenadas de imagen y crece
hacia abajo, asi que "subir" es que y disminuya)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass
class JumpWindow:
    takeoff_idx: int
    apex_idx: int
    landing_idx: int


class JumpPhaseDetector:
    def __init__(
        self,
        baseline_frames: int = 10,
        min_jump_height: float = 0.03,
        liftoff_threshold: float = 0.012,
        min_prominence: float = 0.02,
    ) -> None:
        self.baseline_frames = baseline_frames
        self.min_jump_height = min_jump_height
        self.liftoff_threshold = liftoff_threshold
        self.min_prominence = min_prominence

    def detect(self, hip_y: np.ndarray) -> JumpWindow | None:
        """`hip_y` debe venir ya interpolada/suavizada (ver smoothing.py).
        Devuelve None si no se detecta un salto (equivalente a NO_JUMP_DETECTED)."""
        if len(hip_y) < self.baseline_frames + 3:
            return None
        baseline = float(np.median(hip_y[: self.baseline_frames]))
        height = baseline - hip_y  # positivo = mas arriba que la linea base

        peaks, _ = find_peaks(height, prominence=self.min_prominence)
        if len(peaks) == 0:
            return None
        apex_idx = int(peaks[np.argmax(height[peaks])])
        if height[apex_idx] < self.min_jump_height:
            return None

        takeoff_idx = apex_idx
        while takeoff_idx > 0 and height[takeoff_idx] > self.liftoff_threshold:
            takeoff_idx -= 1

        landing_idx = apex_idx
        last = len(height) - 1
        while landing_idx < last and height[landing_idx] > self.liftoff_threshold:
            landing_idx += 1

        return JumpWindow(takeoff_idx=takeoff_idx, apex_idx=apex_idx, landing_idx=landing_idx)
