"""Lectura de video: metadata, resize y stride configurables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

import cv2


@dataclass
class VideoMeta:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration_sec: float
    size_mb: float


@dataclass
class Frame:
    index: int
    image_bgr: "cv2.typing.MatLike"
    timestamp_ms: int


def read_meta(path: str) -> VideoMeta:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FileNotFoundError(f"No se pudo abrir el video: {path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    duration_sec = frame_count / fps if fps > 0 else 0.0
    size_mb = os.path.getsize(path) / (1024 * 1024)
    return VideoMeta(path, width, height, fps, frame_count, duration_sec, size_mb)


def iter_frames(path: str, target_height: int | None = None, stride: int = 1) -> Iterator[Frame]:
    """Itera frames, opcionalmente reducidos a `target_height` (aspect ratio preservado)
    y tomando 1 de cada `stride` frames."""
    if stride < 1:
        raise ValueError("stride debe ser >= 1")
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FileNotFoundError(f"No se pudo abrir el video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % stride == 0:
                if target_height is not None and frame.shape[0] != target_height:
                    scale = target_height / frame.shape[0]
                    new_w = int(round(frame.shape[1] * scale))
                    frame = cv2.resize(frame, (new_w, target_height), interpolation=cv2.INTER_AREA)
                timestamp_ms = int(round((idx / fps) * 1000))
                yield Frame(idx, frame, timestamp_ms)
            idx += 1
    finally:
        cap.release()


def get_frame(path: str, frame_index: int, target_height: int | None = None):
    """Lee un unico frame por indice (para anotar despegue/apice/aterrizaje
    sin recorrer todo el video). Devuelve None si el indice no existe."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FileNotFoundError(f"No se pudo abrir el video: {path}")
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            return None
        if target_height is not None and frame.shape[0] != target_height:
            scale = target_height / frame.shape[0]
            new_w = int(round(frame.shape[1] * scale))
            frame = cv2.resize(frame, (new_w, target_height), interpolation=cv2.INTER_AREA)
        return frame
    finally:
        cap.release()
