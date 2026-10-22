from dataclasses import dataclass

from app.models.jump_analysis import AnalysisStage


@dataclass(frozen=True)
class AnalysisProgressUpdate:
    stage: AnalysisStage
    frames_processed: int = 0
    # 0 mientras no se conoce
    frames_total: int = 0


@dataclass(frozen=True)
class AnalysisFinished:
    """Aviso a quien sigue el análisis que terminó; el resultado lo lee de la base."""

    analysis_id: int


AnalysisEvent = AnalysisProgressUpdate | AnalysisFinished
