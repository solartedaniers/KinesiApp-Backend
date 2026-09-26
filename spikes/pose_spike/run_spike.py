"""CLI del spike de rendimiento de MediaPipe Pose (Fase 0.5).

Ejemplo:
    python run_spike.py --videos-dir videos --models-dir models \\
        --model-variants lite,full --resolutions original,720,480 --strides 1,2

Ver README.md para instrucciones de descarga de modelos y de donde salen los videos.
"""
from __future__ import annotations

import argparse
import os
import sys


def _set_thread_env_early(argv: list) -> None:
    """Debe correr ANTES de importar mediapipe: TFLite/XNNPACK y OpenBLAS leen
    estas variables de entorno al cargar la libreria nativa, no despues."""
    num_threads = None
    for i, a in enumerate(argv):
        if a == "--num-threads" and i + 1 < len(argv):
            num_threads = argv[i + 1]
        elif a.startswith("--num-threads="):
            num_threads = a.split("=", 1)[1]
    if num_threads is None:
        num_threads = str(os.cpu_count() or 2)
    for var in ("OMP_NUM_THREADS", "TFLITE_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(var, num_threads)


_set_thread_env_early(sys.argv[1:])

from spike.pipeline import RunConfig, run_all  # noqa: E402 (import tardio a proposito, ver arriba)
from spike.report import write_report  # noqa: E402


def _csv(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()]


def _resolution(value: str):
    return None if value == "original" else int(value)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--videos-dir", default="videos", help="Carpeta con videos de entrada (default: videos)")
    p.add_argument("--models-dir", default="models", help="Carpeta con los .task de PoseLandmarker (default: models)")
    p.add_argument("--output-dir", default="output", help="Carpeta de salida (default: output)")
    p.add_argument(
        "--model-variants", type=_csv, default=["lite", "full", "heavy"],
        help="Variantes a probar, separadas por coma (default: lite,full,heavy). "
        "Se espera pose_landmarker_<variante>.task por cada una en --models-dir",
    )
    p.add_argument(
        "--resolutions", type=_csv, default=["original", "720", "480"],
        help="Alturas objetivo en px, o 'original' (default: original,720,480)",
    )
    p.add_argument("--strides", type=_csv, default=["1", "2", "3"], help="Cada cuantos frames procesar (default: 1,2,3)")
    p.add_argument(
        "--num-threads", type=int, default=os.cpu_count() or 2,
        help="Limite de hilos para las librerias nativas (default: os.cpu_count())",
    )
    p.add_argument(
        "--smoothing-window", type=int, default=5,
        help="Ventana de la media movil para suavizar las series de angulos (default: 5)",
    )
    p.add_argument(
        "--baseline-frames", type=int, default=10,
        help="Frames iniciales usados como referencia de 'de pie' para detectar el salto (default: 10)",
    )
    p.add_argument(
        "--min-jump-height", type=float, default=0.03,
        help="Altura minima (unidades normalizadas de cadera) para considerar que hubo salto (default: 0.03)",
    )
    p.add_argument(
        "--liftoff-threshold", type=float, default=0.012,
        help="Umbral de altura para marcar despegue/aterrizaje (default: 0.012)",
    )
    p.add_argument(
        "--visibility-threshold", type=float, default=0.3,
        help="Visibilidad minima de un landmark para considerarlo confiable al dibujar (default: 0.3)",
    )
    p.add_argument(
        "--max-videos", type=int, default=None,
        help="Limite de videos a procesar, util para pruebas rapidas (default: sin limite)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = RunConfig(
        videos_dir=args.videos_dir,
        models_dir=args.models_dir,
        output_dir=args.output_dir,
        model_variants=args.model_variants,
        resolutions=[_resolution(r) for r in args.resolutions],
        strides=[int(s) for s in args.strides],
        smoothing_window=args.smoothing_window,
        baseline_frames=args.baseline_frames,
        min_jump_height=args.min_jump_height,
        liftoff_threshold=args.liftoff_threshold,
        visibility_threshold=args.visibility_threshold,
        max_videos=args.max_videos,
    )
    results = run_all(config)
    os.makedirs(args.output_dir, exist_ok=True)
    summary_path = os.path.join(args.output_dir, "run_summary.md")
    write_report(results, summary_path)
    print(f"Listo. {len(results)} combinaciones procesadas. Resumen en {summary_path}")


if __name__ == "__main__":
    main()
