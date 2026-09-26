"""Orquesta: para cada video x variante de modelo x resolucion x stride,
corre PoseLandmarker, mide tiempo/memoria, calcula angulos, detecta el salto
y guarda frames anotados + un grafico de las series."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import numpy as np

from . import angles as angles_mod
from . import annotate
from . import landmarker as lm_mod
from . import plotting
from . import quality as quality_mod
from . import smoothing
from . import video_source
from .phases import JumpPhaseDetector

_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")


@dataclass
class RunConfig:
    # nota: --num-threads no esta aca porque se aplica como variable de
    # entorno antes de importar mediapipe (ver run_spike.py), no como config
    # que este pipeline consuma directamente.
    videos_dir: str
    models_dir: str
    output_dir: str
    model_variants: list
    resolutions: list  # int | None (None = resolucion original)
    strides: list
    smoothing_window: int
    baseline_frames: int
    min_jump_height: float
    liftoff_threshold: float
    visibility_threshold: float
    max_videos: int | None = None


@dataclass
class CombinationResult:
    video_name: str
    video_size_mb: float
    video_duration_sec: float
    model_variant: str
    resolution: str
    stride: int
    model_load_sec: float
    timing_mean_ms: float
    timing_p95_ms: float
    timing_total_sec: float
    effective_fps: float
    peak_rss_mb: float
    pct_frames_without_pose: float
    visibility_mean_hip: float
    visibility_mean_knee: float
    visibility_mean_ankle: float
    noise_knee_before: float
    noise_knee_after: float
    noise_trunk_before: float
    noise_trunk_after: float
    jump_detected: bool
    knee_angle_at_landing_deg: float | None
    trunk_angle_at_landing_deg: float | None
    landing_depth: float | None


def _find_videos(videos_dir: str) -> list:
    if not os.path.isdir(videos_dir):
        return []
    return sorted(f for f in os.listdir(videos_dir) if f.lower().endswith(_VIDEO_EXTS))


def _model_path(models_dir: str, variant: str) -> str:
    return os.path.join(models_dir, f"pose_landmarker_{variant}.task")


def run_all(config: RunConfig) -> list:
    videos = _find_videos(config.videos_dir)
    if config.max_videos:
        videos = videos[: config.max_videos]
    if not videos:
        print(f"Sin videos en {config.videos_dir}/. Ver README para donde colocarlos.")
        return []

    results = []
    for video_name in videos:
        video_path = os.path.join(config.videos_dir, video_name)
        meta = video_source.read_meta(video_path)
        for variant in config.model_variants:
            model_path = _model_path(config.models_dir, variant)
            if not os.path.isfile(model_path):
                print(f"Aviso: falta {model_path}, se salta la variante '{variant}'.")
                continue
            for resolution in config.resolutions:
                for stride in config.strides:
                    print(f"-> {video_name} | modelo={variant} | res={resolution or 'original'} | stride={stride}")
                    results.append(_run_combination(config, video_name, video_path, meta, variant, model_path, resolution, stride))
    return results


def _run_combination(config, video_name, video_path, meta, variant, model_path, resolution, stride) -> CombinationResult:
    from .timing import FrameTimer, RssSampler

    loaded = lm_mod.load(model_path)
    timer = FrameTimer()
    rss = RssSampler()

    frame_indices, hip_y, knee_angle, trunk_angle = [], [], [], []
    hip_vis, knee_vis, ankle_vis, detected_flags = [], [], [], []

    for frame in video_source.iter_frames(video_path, target_height=resolution, stride=stride):
        t0 = time.perf_counter()
        result = lm_mod.detect(loaded, frame.image_bgr, frame.timestamp_ms)
        timer.record(time.perf_counter() - t0)
        rss.sample()

        frame_indices.append(frame.index)
        if result.pose_landmarks:
            lms = result.pose_landmarks[0]
            side = angles_mod.pick_side(lms)
            a = angles_mod.frame_angles(lms, side)
            detected_flags.append(True)
            hip_y.append(a.hip_y)
            knee_angle.append(a.knee_flexion_deg)
            trunk_angle.append(a.trunk_flexion_deg)
            hip_vis.append(a.hip_visibility)
            knee_vis.append(a.knee_visibility)
            ankle_vis.append(a.ankle_visibility)
        else:
            detected_flags.append(False)
            for series in (hip_y, knee_angle, trunk_angle, hip_vis, knee_vis, ankle_vis):
                series.append(np.nan)

    loaded.landmarker.close()
    stats = timer.stats()
    q = quality_mod.compute_quality(detected_flags, hip_vis, knee_vis, ankle_vis)

    pre = smoothing.LandmarkSeriesPreprocessor(window=config.smoothing_window)
    hip_smooth = pre.process(np.array(hip_y))
    knee_smooth = pre.process(np.array(knee_angle))
    trunk_smooth = pre.process(np.array(trunk_angle))

    detector = JumpPhaseDetector(
        baseline_frames=config.baseline_frames,
        min_jump_height=config.min_jump_height,
        liftoff_threshold=config.liftoff_threshold,
    )
    window = detector.detect(hip_smooth.smoothed)

    combo_dir = os.path.join(
        config.output_dir, os.path.splitext(video_name)[0], variant, f"res-{resolution or 'orig'}_stride-{stride}"
    )
    os.makedirs(combo_dir, exist_ok=True)

    knee_at_landing = trunk_at_landing = landing_depth = None
    if window is not None:
        _annotate_key_frames(video_path, resolution, model_path, window, frame_indices, combo_dir, config.visibility_threshold)
        knee_at_landing = float(knee_smooth.smoothed[window.landing_idx])
        trunk_at_landing = float(trunk_smooth.smoothed[window.landing_idx])
        landing_depth = float(hip_smooth.smoothed[window.landing_idx] - hip_smooth.smoothed[window.apex_idx])
    plotting.plot_series(os.path.join(combo_dir, "series.png"), frame_indices, knee_smooth.smoothed, trunk_smooth.smoothed, window)

    return CombinationResult(
        video_name=video_name,
        video_size_mb=meta.size_mb,
        video_duration_sec=meta.duration_sec,
        model_variant=variant,
        resolution=str(resolution or "original"),
        stride=stride,
        model_load_sec=loaded.load_time_sec,
        timing_mean_ms=stats.mean_ms,
        timing_p95_ms=stats.p95_ms,
        timing_total_sec=stats.total_sec,
        effective_fps=stats.fps,
        peak_rss_mb=rss.peak_mb,
        pct_frames_without_pose=q.pct_without_pose,
        visibility_mean_hip=q.visibility_mean["hip"],
        visibility_mean_knee=q.visibility_mean["knee"],
        visibility_mean_ankle=q.visibility_mean["ankle"],
        noise_knee_before=knee_smooth.noise_before,
        noise_knee_after=knee_smooth.noise_after,
        noise_trunk_before=trunk_smooth.noise_before,
        noise_trunk_after=trunk_smooth.noise_after,
        jump_detected=window is not None,
        knee_angle_at_landing_deg=knee_at_landing,
        trunk_angle_at_landing_deg=trunk_at_landing,
        landing_depth=landing_depth,
    )


def _annotate_key_frames(video_path, resolution, model_path, window, frame_indices, combo_dir, visibility_threshold) -> None:
    """Guarda frames anotados en despegue, apice, aterrizaje y 2 puntos
    intermedios. Usa un landmarker en modo IMAGE aparte, solo para dibujar
    (el modo VIDEO no se puede re-consultar retroactivamente por indice)."""
    mid_up = (window.takeoff_idx + window.apex_idx) // 2
    mid_down = (window.apex_idx + window.landing_idx) // 2
    targets = {
        "despegue": window.takeoff_idx,
        "mid_ascenso": mid_up,
        "apice": window.apex_idx,
        "mid_descenso": mid_down,
        "aterrizaje": window.landing_idx,
    }
    img_loaded = lm_mod.load_image_mode(model_path)
    try:
        for label, pos in targets.items():
            frame_idx = frame_indices[pos]
            frame = video_source.get_frame(video_path, frame_idx, target_height=resolution)
            if frame is None:
                continue
            result = lm_mod.detect_image(img_loaded, frame)
            if not result.pose_landmarks:
                continue
            out_path = os.path.join(combo_dir, f"{label}_frame{frame_idx}.png")
            annotate.save_annotated(out_path, frame, result.pose_landmarks[0], label, visibility_threshold)
    finally:
        img_loaded.landmarker.close()
