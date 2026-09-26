"""Wrapper delgado sobre PoseLandmarker (Tasks API) en modo VIDEO, CPU."""
from __future__ import annotations

import time
from dataclasses import dataclass

import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark as Landmark


@dataclass
class LoadedLandmarker:
    landmarker: vision.PoseLandmarker
    load_time_sec: float


def load(model_path: str, num_poses: int = 1) -> LoadedLandmarker:
    """Carga el modelo .task en CPU y modo VIDEO, midiendo el tiempo de carga.

    Nota (thread limiting): la Tasks API de mediapipe en esta version
    (`PoseLandmarkerOptions`/`BaseOptions`) no expone un parametro de numero
    de hilos para el delegado CPU. El limite real de CPU para el spike se
    aplica a nivel de proceso/contenedor (variables de entorno
    OMP_NUM_THREADS/TFLITE_NUM_THREADS seteadas antes de importar mediapipe,
    y sobre todo `docker run --cpus`), no aqui. Ver README.
    """
    t0 = time.perf_counter()
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path, delegate=BaseOptions.Delegate.CPU),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=num_poses,
    )
    landmarker = vision.PoseLandmarker.create_from_options(options)
    load_time = time.perf_counter() - t0
    return LoadedLandmarker(landmarker, load_time)


def _to_mp_image(image_bgr):
    import cv2

    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


def detect(loaded: LoadedLandmarker, image_bgr, timestamp_ms: int):
    """Corre deteccion sobre un frame BGR (numpy array) y devuelve el resultado crudo."""
    return loaded.landmarker.detect_for_video(_to_mp_image(image_bgr), timestamp_ms)


def load_image_mode(model_path: str, num_poses: int = 1) -> LoadedLandmarker:
    """Variante en modo IMAGE, usada solo para anotar frames sueltos (despegue,
    apice, aterrizaje) fuera de la secuencia temporal del modo VIDEO."""
    t0 = time.perf_counter()
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path, delegate=BaseOptions.Delegate.CPU),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=num_poses,
    )
    landmarker = vision.PoseLandmarker.create_from_options(options)
    return LoadedLandmarker(landmarker, time.perf_counter() - t0)


def detect_image(loaded: LoadedLandmarker, image_bgr):
    return loaded.landmarker.detect(_to_mp_image(image_bgr))
