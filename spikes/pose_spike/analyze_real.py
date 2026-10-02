"""Analisis desechable de los 4 videos reales (spike, no produccion).

Etapa 1 (`extract`, un subproceso por video x variante): corre PoseLandmarker en modo VIDEO,
guarda los 33 landmarks de cada frame y mide tiempo por frame y RSS pico con un hilo de
muestreo (5 ms), en un proceso limpio para que la memoria de un modelo no contamine al otro.

Etapa 2 (`analyze`): cortes de escena, calidad de deteccion, metricas por movimiento
(salto / sentadilla), concordancia entre variantes y frames anotados.

Uso:  python analyze_real.py            (corre todo)
      python analyze_real.py analyze    (sólo la etapa 2, sobre landmarks ya extraidos)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output", "real")
VARIANTS = ["lite", "full", "heavy"]
VIDEOS = {
    # nombre: (movimiento, vista de camara observada al revisar los frames)
    # Corrida 2026-10-01 (videos propios). La anterior (grabaciones de pantalla) quedó en output/real_pantalla/
    "salto_bien_echo.mp4": ("jump", "oblicua"),
    "salto_mal_echo.mp4": ("jump", "oblicua"),
    "sentadilla_bien_echa.mp4": ("squat", "oblicua"),
    "sentadilla_mal_echa.mp4": ("squat", "oblicua"),
}

# Indices BlazePose
L_SH, R_SH, L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK, L_HEEL, R_HEEL, L_TOE, R_TOE = 11, 12, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32
SIDES = {
    "left": dict(sh=L_SH, hip=L_HIP, knee=L_KNEE, ank=L_ANK, heel=L_HEEL, toe=L_TOE),
    "right": dict(sh=R_SH, hip=R_HIP, knee=R_KNEE, ank=R_ANK, heel=R_HEEL, toe=R_TOE),
}


# ----------------------------------------------------------------------------- etapa 1
# Videos con varias personas: cuantas poses pedir y a quien seguir (ver REPORT.md, salto_mala)
# Vacío: esta corrida usa num_poses=1, el modo de producción
MULTI_PERSON: dict = {}


def _hip_center(pose) -> np.ndarray:
    return np.array([(pose[L_HIP].x + pose[R_HIP].x) / 2, (pose[L_HIP].y + pose[R_HIP].y) / 2])


def _pick_tracked(poses, previous: np.ndarray | None, seed: str):
    """Sin IDs de persona en MediaPipe: se sigue a la persona por cercania de la cadera al frame
    anterior; en el primer frame, la semilla (p. ej. la persona mas a la derecha)."""
    if previous is None:
        return max(poses, key=lambda pose: _hip_center(pose)[0]) if seed == "rightmost" else poses[0]
    return min(poses, key=lambda pose: np.linalg.norm(_hip_center(pose) - previous))


def extract(video: str, variant: str) -> None:
    import psutil

    proc = psutil.Process()
    baseline_rss = proc.memory_info().rss
    peak = [baseline_rss]
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            peak[0] = max(peak[0], proc.memory_info().rss)
            time.sleep(0.005)

    threading.Thread(target=sampler, daemon=True).start()

    sys.path.insert(0, HERE)
    from spike import landmarker as lm_mod, video_source

    multi = MULTI_PERSON.get(video)
    loaded = lm_mod.load(os.path.join(HERE, "models", f"pose_landmarker_{variant}.task"), num_poses=multi["num_poses"] if multi else 1)
    frames, times, detected = [], [], []
    tracked_hip = None
    for frame in video_source.iter_frames(os.path.join(HERE, "videos", video)):
        t0 = time.perf_counter()
        result = lm_mod.detect(loaded, frame.image_bgr, frame.timestamp_ms)
        times.append(time.perf_counter() - t0)
        if result.pose_landmarks:
            lms = _pick_tracked(result.pose_landmarks, tracked_hip, multi["seed"]) if multi else result.pose_landmarks[0]
            tracked_hip = _hip_center(lms)
            frames.append([[p.x, p.y, p.visibility or 0.0, p.presence or 0.0] for p in lms])
            detected.append(True)
        else:
            frames.append(np.full((33, 4), np.nan).tolist())
            detected.append(False)
    loaded.landmarker.close()
    stop.set()

    out_dir = os.path.join(OUT, video[:-4], variant)
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, "landmarks.npz"), lms=np.array(frames, dtype=float), detected=np.array(detected))
    t = np.array(times) * 1000
    with open(os.path.join(out_dir, "perf.json"), "w") as f:
        json.dump(
            {
                "frames": len(t),
                "load_sec": loaded.load_time_sec,
                "mean_ms": float(t.mean()),
                "p95_ms": float(np.percentile(t, 95)),
                "fps": float(1000 / t.mean()),
                "rss_baseline_mb": baseline_rss / 2**20,
                "rss_peak_mb": peak[0] / 2**20,
            },
            f,
        )


def run_extractions(only: list[str] | None = None) -> None:
    for video in only or VIDEOS:
        for variant in VARIANTS:
            print(f"extrayendo {video} [{variant}]", flush=True)
            subprocess.run([sys.executable, __file__, "extract", video, variant], check=True)


# ----------------------------------------------------------------------------- utilidades
def angle(a, v, c) -> float:
    """Angulo interno en v (grados), 2D en coordenadas normalizadas de imagen."""
    v1, v2 = a - v, c - v
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    if n == 0 or np.isnan(n):
        return np.nan
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1, 1))))


def xy(lms, i, aspect):
    # x se escala por el aspecto (ancho/alto) para que los angulos no se deformen en videos verticales
    return np.array([lms[i, 0] * aspect, lms[i, 1]])


def scene_cuts(video_path: str, threshold: float = 0.8) -> list[int]:
    """Frames donde empieza una escena nueva (correlacion de histograma HSV entre frames consecutivos).
    0.8 y no 0.6: al grabar una pantalla los cortes reales quedan suavizados (salto_buena f64 = 0.75)."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    cuts, prev, idx = [0], None, 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        hist = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        if prev is not None and cv2.compareHist(prev, hist, cv2.HISTCMP_CORREL) < threshold:
            cuts.append(idx)
        prev, idx = hist, idx + 1
    cap.release()
    return cuts


def segments(n: int, cuts: list[int], min_len: int = 12) -> list[tuple[int, int]]:
    bounds = cuts + [n]
    return [(s, e) for s, e in zip(bounds[:-1], bounds[1:]) if e - s >= min_len]


def smooth(series: np.ndarray, window: int = 5) -> np.ndarray:
    sys.path.insert(0, HERE)
    from spike.smoothing import LandmarkSeriesPreprocessor

    return LandmarkSeriesPreprocessor(window).process(series).smoothed


def best_side(lms_seq) -> str:
    vis = {s: np.nanmean(lms_seq[:, [ix["hip"], ix["knee"], ix["ank"]], 2]) for s, ix in SIDES.items()}
    return max(vis, key=vis.get)


# ----------------------------------------------------------------------------- metricas
def tracking_stability(lms, detected) -> dict:
    """¿La persona rastreada es siempre la misma? Sin IDs, dos firmas de que el rastreo saltó a otra
    figura (p. ej. el reflejo en un espejo): (1) el centro de la cadera se desplaza más de medio
    torso entre frames consecutivos; (2) el torso (hombros-caderas) mide menos del 60 % de su
    mediana, porque una figura más lejana se ve más chica."""
    hip = np.nanmean(lms[:, [L_HIP, R_HIP], :2], axis=1)
    sh = np.nanmean(lms[:, [L_SH, R_SH], :2], axis=1)
    torso = np.linalg.norm(sh - hip, axis=1)
    median_torso = float(np.nanmedian(torso))
    step = np.linalg.norm(np.diff(hip, axis=0), axis=1) / median_torso
    jumps = np.where(step > 0.5)[0] + 1
    small = np.where(torso < 0.6 * median_torso)[0]
    lost_runs, run = [], 0
    for ok in detected:
        run = 0 if ok else run + 1
        if run == 1:
            lost_runs.append(1)
        elif run > 1:
            lost_runs[-1] += 1
    return {
        "hip_jumps": [int(i) for i in jumps],
        "small_torso_frames": [int(i) for i in small],
        "frames_without_pose": int((~detected).sum()),
        "longest_gap_frames": max(lost_runs, default=0),
        "max_step_torso": float(np.nanmax(step)) if len(step) else 0.0,
    }


def quality(lms, detected) -> dict:
    out = {"pct_detected": float(detected.mean() * 100)}
    for joint, idxs in {"cadera": (L_HIP, R_HIP), "rodilla": (L_KNEE, R_KNEE), "tobillo": (L_ANK, R_ANK)}.items():
        vis = lms[detected][:, idxs, 2].ravel()
        out[f"vis_{joint}_media"] = float(np.nanmean(vis))
        out[f"vis_{joint}_p10"] = float(np.nanpercentile(vis, 10))
    return out


def knee_series(lms, side, aspect):
    ix = SIDES[side]
    return np.array([angle(xy(f, ix["hip"], aspect), xy(f, ix["knee"], aspect), xy(f, ix["ank"], aspect)) for f in lms])


def trunk_series(lms, side, aspect):
    ix = SIDES[side]
    out = []
    for f in lms:
        v = xy(f, ix["sh"], aspect) - xy(f, ix["hip"], aspect)
        out.append(np.nan if np.isnan(v).any() else float(np.degrees(np.arccos(np.clip(-v[1] / np.linalg.norm(v), -1, 1)))))
    return np.array(out)


def fppa(f, side, aspect) -> float:
    """Frontal plane projection angle con signo: desviacion de la rodilla respecto de la linea
    cadera-tobillo. Positivo = rodilla hacia la linea media (valgo), negativo = varo."""
    ix = SIDES[side]
    hip, knee, ank = xy(f, ix["hip"], aspect), xy(f, ix["knee"], aspect), xy(f, ix["ank"], aspect)
    dev = 180 - angle(hip, knee, ank)
    midline_x = (f[L_HIP, 0] + f[R_HIP, 0]) / 2 * aspect
    # x de la rodilla respecto de la recta cadera-tobillo a su misma altura
    t = (knee[1] - hip[1]) / (ank[1] - hip[1]) if ank[1] != hip[1] else 0.5
    line_x = hip[0] + t * (ank[0] - hip[0])
    toward_mid = abs(knee[0] - midline_x) < abs(line_x - midline_x)
    return float(dev if toward_mid else -dev)


def jump_events(lms, detected, segs, fps) -> list[dict]:
    """Un salto por cada apice de la cadera (pico limpio de la trayectoria vertical, que el
    contramovimiento no confunde). Desde el apice: el contacto es el primer frame en que el punto
    mas bajo del pie vuelve a su suelo LOCAL (percentil 90 en +-1 s, porque la persona se acerca y
    se aleja de la camara); el despegue, el ultimo frame en el suelo antes del apice. El punto mas
    bajo del pie (tobillo, talon o punta) evita confundir "en puntas de pie" con "en el aire"."""
    from scipy.signal import find_peaks

    events = []
    left_foot = np.nanmax(lms[:, [L_ANK, L_HEEL, L_TOE], 1], axis=1)
    right_foot = np.nanmax(lms[:, [R_ANK, R_HEEL, R_TOE], 1], axis=1)
    foot_y = np.nanmean(np.stack([left_foot, right_foot], axis=1), axis=1)
    hip_y = np.nanmean(lms[:, [L_HIP, R_HIP], 1], axis=1)
    shoulder_y = np.nanmean(lms[:, [L_SH, R_SH], 1], axis=1)
    body = np.nanmedian(np.abs(foot_y - shoulder_y))
    half = max(1, int(round(fps)))
    for s, e in segs:
        foot = smooth(foot_y[s:e], 3)
        hip = smooth(hip_y[s:e], 3)
        ground = np.array([np.nanpercentile(foot[max(0, i - half): i + half + 1], 90) for i in range(len(foot))])
        airborne = lambda i, k: foot[i] < ground[i] - k * body  # noqa: E731
        apexes, _ = find_peaks(-hip, prominence=0.08, distance=max(1, int(0.6 * fps)))
        for apex in apexes:
            if not airborne(apex, 0.06):  # en el apice los pies tienen que estar en el aire
                continue
            land = apex
            while land < len(foot) - 1 and airborne(land, 0.03):
                land += 1
            take = apex
            while take > 0 and airborne(take, 0.03):
                take -= 1
            events.append({
                "takeoff": s + take, "apex": s + int(apex), "landing": s + land,
                "flight_ms": (land - take) / fps * 1000, "segment": [s, e],
            })
    return events


def squat_bottoms(knee, segs) -> list[int]:
    from scipy.signal import find_peaks

    bottoms = []
    for s, e in segs:
        seg = smooth(knee[s:e], 5)
        if np.isnan(seg).all():
            continue
        peaks, _ = find_peaks(-seg, prominence=25, distance=10)
        bottoms += [s + int(p) for p in peaks if seg[p] < 130]  # < 130° interno = flexion real, no ruido de pie
    return bottoms


def squat_frame_metrics(f, side, aspect) -> dict:
    ix = SIDES[side]
    knee, ank, heel, toe = (xy(f, ix[k], aspect) for k in ("knee", "ank", "heel", "toe"))
    shank = np.linalg.norm(knee - ank)
    facing = np.sign(toe[0] - heel[0]) or 1.0
    return {
        # > 0: el talon esta mas alto que la punta del pie (talon levantado), en largos de pierna
        "heel_lift": float((toe[1] - heel[1]) / shank),
        # > 0: la rodilla pasa por delante de la punta del pie, en largos de pierna
        "knee_over_toe": float((knee[0] - toe[0]) * facing / shank),
    }


# ----------------------------------------------------------------------------- anotacion
def save_annotated(video, frame_idx, f, side, aspect, label, path, lines):
    import cv2

    cap = cv2.VideoCapture(os.path.join(HERE, "videos", video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, img = cap.read()
    cap.release()
    if not ok:
        return
    h, w = img.shape[:2]
    scale = 2  # 474x850 es chico: se agranda para que se lea
    img = cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    px = lambda i: (int(f[i, 0] * w * scale), int(f[i, 1] * h * scale))  # noqa: E731
    for s_name, ix in SIDES.items():
        color = (0, 255, 0) if s_name == side else (255, 160, 0)
        chain = [ix["sh"], ix["hip"], ix["knee"], ix["ank"], ix["heel"], ix["toe"], ix["ank"]]
        for a, b in zip(chain[:-1], chain[1:]):
            if not np.isnan(f[a, 0]) and not np.isnan(f[b, 0]):
                cv2.line(img, px(a), px(b), color, 3)
        for i in chain:
            if not np.isnan(f[i, 0]):
                cv2.circle(img, px(i), 6, (0, 0, 255), -1)
    for (a, b) in [(L_SH, R_SH), (L_HIP, R_HIP)]:
        if not np.isnan(f[a, 0]) and not np.isnan(f[b, 0]):
            cv2.line(img, px(a), px(b), (200, 200, 200), 2)
    text = [label] + lines
    for k, t in enumerate(text):
        y = 34 + k * 30
        cv2.putText(img, t, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, t, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(path, img)


# ----------------------------------------------------------------------------- etapa 2
def analyze() -> dict:
    import cv2

    results = {}
    for video, (movement, view) in VIDEOS.items():
        path = os.path.join(HERE, "videos", video)
        cap = cv2.VideoCapture(path)
        fps, w, h = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        cap.release()
        aspect = w / h
        cuts = scene_cuts(path)
        per_variant = {}
        knees = {}
        for variant in VARIANTS:
            d = os.path.join(OUT, video[:-4], variant)
            data = np.load(os.path.join(d, "landmarks.npz"))
            lms, detected = data["lms"], data["detected"]
            perf = json.load(open(os.path.join(d, "perf.json")))
            segs = segments(len(lms), cuts)
            side = best_side(lms[detected])
            knee = knee_series(lms, side, aspect)
            trunk = trunk_series(lms, side, aspect)
            knees[variant] = knee
            r = {"perf": perf, "quality": quality(lms, detected), "tracking": tracking_stability(lms, detected), "side": side, "segments": segs}

            if movement == "jump":
                events = jump_events(lms, detected, segs, fps)
                rows = []
                for ev in events:
                    land = ev["landing"]
                    window = list(range(land, min(land + int(0.3 * fps) + 1, len(lms))))  # 300 ms tras el contacto
                    knee_win = knee[window]
                    row = {
                        **ev,
                        "knee_at_contact": float(knee[land]),
                        "knee_min_300ms": float(np.nanmin(knee_win)),
                        "knee_min_frame": int(window[int(np.nanargmin(knee_win))]),
                        "trunk_at_contact": float(trunk[land]),
                        "trunk_max_300ms": float(np.nanmax(trunk[window])),
                        # Aterrizaje en los ultimos 3 frames: los pies salieron del cuadro, no es un contacto real
                        "valid": land < len(lms) - 3,
                    }
                    if view == "frontal":
                        f = lms[land]
                        row["fppa_left_contact"] = fppa(f, "left", aspect)
                        row["fppa_right_contact"] = fppa(f, "right", aspect)
                        row["fppa_max_valgus_300ms"] = float(
                            np.nanmax([max(fppa(lms[i], "left", aspect), fppa(lms[i], "right", aspect)) for i in window])
                        )
                    rows.append(row)
                r["jumps"] = rows
                valid = [row for row in rows if row["valid"]]
                r["jump_summary"] = {
                    "jumps_detected": len(rows),
                    "jumps_valid": len(valid),
                    **{f"{k}_median": (float(np.median([row[k] for row in valid])) if valid else None)
                       for k in ("knee_at_contact", "knee_min_300ms", "trunk_max_300ms", "flight_ms")},
                }
                # Frame clave: la maxima flexion tras el contacto del primer salto valido
                key = valid[0]["knee_min_frame"] if valid else None
                key_label = "aterrizaje max flexion"
            else:
                bottoms = squat_bottoms(knee, segs)
                ix = SIDES[side]
                standing = [i for i in range(len(lms)) if knee[i] > 160 and detected[i]]
                heel_standing = float(np.nanmedian([squat_frame_metrics(lms[i], side, aspect)["heel_lift"] for i in standing])) if standing else 0.0
                rows = []
                for b in bottoms:
                    m = squat_frame_metrics(lms[b], side, aspect)
                    vis_ok = lms[b, ix["knee"], 2] >= 0.5 and lms[b, ix["ank"], 2] >= 0.5
                    rows.append({"frame": b, "knee": float(knee[b]), "trunk": float(trunk[b]), **m,
                                 "heel_lift_rel": m["heel_lift"] - heel_standing, "vis_ok": bool(vis_ok)})
                r["reps"] = rows
                r["heel_standing"] = heel_standing
                valid = [row for row in rows if row["vis_ok"]]
                r["squat_summary"] = {
                    "reps_detected": len(rows),
                    "reps_valid": len(valid),
                    **{f"{k}_median": (float(np.median([row[k] for row in valid])) if valid else None)
                       for k in ("knee", "trunk", "heel_lift_rel", "knee_over_toe")},
                }
                key = min(valid or rows, key=lambda x: x["knee"])["frame"] if rows else None
                key_label = "punto mas bajo"
            r["key_frame"] = key
            if key is not None:
                lines = [f"{variant} | lado {side} | frame {key}", f"rodilla interna {knee[key]:.0f} (flexion {180 - knee[key]:.0f})", f"tronco {trunk[key]:.0f} vs vertical"]
                if view == "frontal":
                    lines.append(f"FPPA izq {fppa(lms[key], 'left', aspect):+.0f} der {fppa(lms[key], 'right', aspect):+.0f} (+ = valgo)")
                if movement == "squat":
                    m = squat_frame_metrics(lms[key], side, aspect)
                    lines.append(f"talon {m['heel_lift']:+.2f}  rodilla-punta {m['knee_over_toe']:+.2f}")
                png = os.path.join(OUT, video[:-4], variant, f"{key_label.replace(' ', '_')}_frame{key}.png")
                save_annotated(video, key, lms[key], side, aspect, f"{video[:-4]} - {key_label}", png, lines)
                r["key_png"] = os.path.relpath(png, HERE)
            per_variant[variant] = r

        # Concordancia: diferencia media del angulo de rodilla de lite/full contra heavy (sin verdad de terreno)
        agree = {}
        for variant in ("lite", "full"):
            diff = np.abs(knees[variant] - knees["heavy"])
            agree[variant] = {"mae_vs_heavy": float(np.nanmean(diff)), "p90_vs_heavy": float(np.nanpercentile(diff, 90))}
        results[video] = {"movement": movement, "view": view, "fps": fps, "size": [int(w), int(h)], "cuts": cuts, "variants": per_variant, "agreement": agree}
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=2, default=float)
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "extract":
        extract(sys.argv[2], sys.argv[3])
    elif len(sys.argv) > 1 and sys.argv[1] == "analyze":
        analyze()
        print("analisis listo:", os.path.join(OUT, "results.json"))
    elif len(sys.argv) > 1 and sys.argv[1] == "reextract":
        run_extractions(sys.argv[2:])
        analyze()
        print("listo:", os.path.join(OUT, "results.json"))
    else:
        run_extractions()
        analyze()
        print("listo:", os.path.join(OUT, "results.json"))
