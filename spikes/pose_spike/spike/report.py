"""Genera una tabla markdown con los resultados crudos de la corrida.

Esto NO es el REPORT.md final (ese lo escribe una persona con las
conclusiones); es un volcado de datos para armarlo con evidencia real.
"""
from __future__ import annotations

_COLUMNS = [
    ("video_name", "video"),
    ("video_size_mb", "tamano_mb"),
    ("video_duration_sec", "duracion_s"),
    ("model_variant", "modelo"),
    ("resolution", "resolucion"),
    ("stride", "stride"),
    ("model_load_sec", "carga_modelo_s"),
    ("timing_mean_ms", "t_medio_ms"),
    ("timing_p95_ms", "t_p95_ms"),
    ("effective_fps", "fps_efectivo"),
    ("peak_rss_mb", "rss_pico_mb"),
    ("pct_frames_without_pose", "pct_sin_pose"),
    ("visibility_mean_hip", "vis_cadera"),
    ("visibility_mean_knee", "vis_rodilla"),
    ("visibility_mean_ankle", "vis_tobillo"),
    ("noise_knee_before", "ruido_rodilla_antes"),
    ("noise_knee_after", "ruido_rodilla_despues"),
    ("jump_detected", "salto_detectado"),
    ("knee_angle_at_landing_deg", "rodilla_aterrizaje_deg"),
    ("trunk_angle_at_landing_deg", "tronco_aterrizaje_deg"),
    ("landing_depth", "profundidad_aterrizaje"),
]


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def build_markdown_table(results: list) -> str:
    if not results:
        return "_Sin resultados: no habia videos/modelos disponibles._\n"
    header = "| " + " | ".join(label for _, label in _COLUMNS) + " |"
    sep = "|" + "|".join("---" for _ in _COLUMNS) + "|"
    rows = []
    for r in results:
        row = "| " + " | ".join(_fmt(getattr(r, field)) for field, _ in _COLUMNS) + " |"
        rows.append(row)
    return "\n".join([header, sep, *rows]) + "\n"


def write_report(results: list, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Resultados crudos de la corrida del spike\n\n")
        f.write(build_markdown_table(results))
