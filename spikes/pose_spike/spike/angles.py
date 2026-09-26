"""Calculo de flexion de rodilla y de tronco a partir de landmarks (vista lateral).

Indices de landmarks segun el modelo BlazePose de 33 puntos usado por
PoseLandmarker: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28

_SIDE_INDICES = {
    "left": {"shoulder": LEFT_SHOULDER, "hip": LEFT_HIP, "knee": LEFT_KNEE, "ankle": LEFT_ANKLE},
    "right": {"shoulder": RIGHT_SHOULDER, "hip": RIGHT_HIP, "knee": RIGHT_KNEE, "ankle": RIGHT_ANKLE},
}


@dataclass
class FrameAngles:
    knee_flexion_deg: float
    trunk_flexion_deg: float
    hip_y: float
    ankle_y: float
    hip_visibility: float
    knee_visibility: float
    ankle_visibility: float


def pick_side(landmarks) -> str:
    """En vista lateral un lado queda mas de frente a la camara; se elige el
    de mayor visibilidad promedio entre cadera/rodilla/tobillo."""
    def avg_vis(side: str) -> float:
        idx = _SIDE_INDICES[side]
        points = [landmarks[idx["hip"]], landmarks[idx["knee"]], landmarks[idx["ankle"]]]
        return sum((p.visibility or 0.0) for p in points) / len(points)

    return "left" if avg_vis("left") >= avg_vis("right") else "right"


def _angle_at_vertex(a, vertex, c) -> float:
    """Angulo en grados en `vertex`, entre los segmentos vertex->a y vertex->c."""
    v1 = (a.x - vertex.x, a.y - vertex.y)
    v2 = (c.x - vertex.x, c.y - vertex.y)
    ang1 = math.atan2(v1[1], v1[0])
    ang2 = math.atan2(v2[1], v2[0])
    diff = math.degrees(ang1 - ang2)
    return abs((diff + 180) % 360 - 180)


def _angle_from_vertical(hip, shoulder) -> float:
    """Angulo del tronco (cadera->hombro) respecto a la vertical de la imagen.
    0 = tronco erguido; crece con la inclinacion, sin distinguir adelante/atras
    (suficiente para un spike de factibilidad)."""
    vx, vy = shoulder.x - hip.x, shoulder.y - hip.y
    mag = math.hypot(vx, vy)
    if mag == 0:
        return 0.0
    cos_a = max(-1.0, min(1.0, -vy / mag))  # vertical "hacia arriba" en imagen = (0, -1)
    return math.degrees(math.acos(cos_a))


def frame_angles(landmarks, side: str) -> FrameAngles:
    idx = _SIDE_INDICES[side]
    hip, knee, ankle, shoulder = (
        landmarks[idx["hip"]], landmarks[idx["knee"]], landmarks[idx["ankle"]], landmarks[idx["shoulder"]],
    )
    return FrameAngles(
        knee_flexion_deg=_angle_at_vertex(hip, knee, ankle),
        trunk_flexion_deg=_angle_from_vertical(hip, shoulder),
        hip_y=hip.y,
        ankle_y=ankle.y,
        hip_visibility=hip.visibility or 0.0,
        knee_visibility=knee.visibility or 0.0,
        ankle_visibility=ankle.visibility or 0.0,
    )
