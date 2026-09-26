"""Dibuja el esqueleto (cadena hombro-cadera-rodilla-tobillo) sobre un frame.

No se usa `mediapipe.solutions.drawing_utils`: el build de mediapipe instalado
(Tasks API, ver README) no incluye el modulo `solutions`. Se dibuja a mano con
OpenCV, que ya es una dependencia del spike.
"""
from __future__ import annotations

import cv2

_CONNECTIONS = [(11, 12), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28)]
_POINTS = (11, 12, 23, 24, 25, 26, 27, 28)


def draw_skeleton(image_bgr, landmarks, visibility_threshold: float = 0.3):
    img = image_bgr.copy()
    h, w = img.shape[:2]

    def px(lm):
        return int(lm.x * w), int(lm.y * h)

    for a, b in _CONNECTIONS:
        la, lb = landmarks[a], landmarks[b]
        if (la.visibility or 0) < visibility_threshold or (lb.visibility or 0) < visibility_threshold:
            continue
        cv2.line(img, px(la), px(lb), (0, 255, 0), 2)
    for i in _POINTS:
        lm = landmarks[i]
        if (lm.visibility or 0) < visibility_threshold:
            continue
        cv2.circle(img, px(lm), 4, (0, 0, 255), -1)
    return img


def save_annotated(path: str, image_bgr, landmarks, label: str = "", visibility_threshold: float = 0.3) -> None:
    img = draw_skeleton(image_bgr, landmarks, visibility_threshold)
    if label:
        cv2.putText(img, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(path, img)
