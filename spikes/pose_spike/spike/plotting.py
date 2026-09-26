"""Grafica las series de angulos con las fases del salto marcadas."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # sin display, corre en servidor/CI/Docker
import matplotlib.pyplot as plt


def plot_series(out_path: str, frame_indices, knee_series, trunk_series, jump_window) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(frame_indices, knee_series, label="Flexion rodilla (deg)")
    ax.plot(frame_indices, trunk_series, label="Flexion tronco (deg)")
    if jump_window is not None:
        markers = [
            (jump_window.takeoff_idx, "green", "Despegue"),
            (jump_window.apex_idx, "orange", "Apice"),
            (jump_window.landing_idx, "red", "Aterrizaje"),
        ]
        for x, color, text in markers:
            ax.axvline(frame_indices[x], color=color, linestyle="--", label=text)
    ax.set_xlabel("Frame")
    ax.set_ylabel("Grados")
    ax.legend(loc="upper right", fontsize="small")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
