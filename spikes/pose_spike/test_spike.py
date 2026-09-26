"""Auto-chequeo minimo de la logica pura (sin mediapipe/video real):
suavizado, deteccion de fases y calculo de angulos sobre datos sinteticos.

Correr: python test_spike.py
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np

from spike.angles import _angle_at_vertex, _angle_from_vertical, pick_side
from spike.phases import JumpPhaseDetector
from spike.smoothing import LandmarkSeriesPreprocessor, interpolate_gaps


def _lm(x, y, visibility=1.0):
    return SimpleNamespace(x=x, y=y, visibility=visibility)


def test_angle_at_vertex_right_angle():
    a, vertex, c = _lm(0, -1), _lm(0, 0), _lm(1, 0)
    assert math.isclose(_angle_at_vertex(a, vertex, c), 90.0, abs_tol=1e-6)


def test_angle_at_vertex_straight_leg():
    hip, knee, ankle = _lm(0, -1), _lm(0, 0), _lm(0, 1)
    assert math.isclose(_angle_at_vertex(hip, knee, ankle), 180.0, abs_tol=1e-6)


def test_angle_from_vertical_upright_trunk():
    hip, shoulder = _lm(0, 1), _lm(0, 0)
    assert math.isclose(_angle_from_vertical(hip, shoulder), 0.0, abs_tol=1e-6)


def test_angle_from_vertical_45deg_lean():
    hip, shoulder = _lm(0, 1), _lm(1, 0)
    assert math.isclose(_angle_from_vertical(hip, shoulder), 45.0, abs_tol=1e-6)


def test_pick_side_prefers_higher_visibility():
    landmarks = [_lm(0, 0, 0.0)] * 33
    landmarks = list(landmarks)
    for i in (11, 23, 25, 27):
        landmarks[i] = _lm(0, 0, 0.9)  # left
    for i in (12, 24, 26, 28):
        landmarks[i] = _lm(0, 0, 0.2)  # right
    assert pick_side(landmarks) == "left"


def test_interpolate_gaps_fills_nan():
    series = np.array([1.0, np.nan, 3.0])
    out = interpolate_gaps(series)
    assert not np.isnan(out).any()
    assert math.isclose(out[1], 2.0, abs_tol=1e-6)


def test_smoothing_reduces_noise():
    rng = np.random.default_rng(0)
    series = np.sin(np.linspace(0, 6, 100)) + rng.normal(0, 0.2, 100)
    result = LandmarkSeriesPreprocessor(window=5).process(series)
    assert result.noise_after < result.noise_before


def _synthetic_jump_series(n=60, baseline=0.6, apex_frame=30, amplitude=0.1):
    """Cadera quieta, sube y baja como un salto, y vuelve a la linea base."""
    t = np.arange(n)
    height = amplitude * np.exp(-((t - apex_frame) ** 2) / (2 * 6.0**2))
    return baseline - height


def test_jump_phase_detector_finds_window():
    series = _synthetic_jump_series()
    detector = JumpPhaseDetector(baseline_frames=10, min_jump_height=0.03, liftoff_threshold=0.012)
    window = detector.detect(series)
    assert window is not None
    assert window.takeoff_idx < window.apex_idx < window.landing_idx
    assert 25 <= window.apex_idx <= 35


def test_jump_phase_detector_returns_none_when_flat():
    series = np.full(60, 0.6) + np.random.default_rng(1).normal(0, 0.001, 60)
    detector = JumpPhaseDetector(baseline_frames=10, min_jump_height=0.03, liftoff_threshold=0.012)
    assert detector.detect(series) is None


def _run_all():
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\n{len(tests)} chequeos pasaron.")


if __name__ == "__main__":
    _run_all()
