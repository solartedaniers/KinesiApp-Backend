from kinesiapp.common.v1 import movement_pb2


class RiskLevelClassifier:
    """Paso el risk_score al nivel del contrato con los cortes configurados, para que el frontend no los replique."""

    def __init__(self, moderate: float, high: float) -> None:
        if not moderate <= high:
            raise ValueError("The moderate cut must not be above the high cut")
        self._moderate = moderate
        self._high = high

    def level(self, risk_score: float | None) -> movement_pb2.RiskLevel.ValueType:
        if risk_score is None:
            return movement_pb2.RISK_LEVEL_UNSPECIFIED
        if risk_score >= self._high:
            return movement_pb2.RISK_LEVEL_HIGH
        if risk_score >= self._moderate:
            return movement_pb2.RISK_LEVEL_MODERATE
        return movement_pb2.RISK_LEVEL_LOW
