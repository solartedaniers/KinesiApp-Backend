from dataclasses import dataclass

from kinesiapp.common.v1 import movement_pb2


@dataclass(frozen=True)
class KneeReading:
    """Lectura de la rodilla de un análisis para el resumen: mediana de los picos y rango sin riesgo."""

    median_peak_degrees: float | None
    target: movement_pb2.AngleRange | None


class KneeReadingExtractor:
    """Saco la lectura de la rodilla de las señales que guardó la IA, sin umbrales propios.

    El rango sin riesgo es donde ninguna rampa de rodilla suma: una señal donde menos flexión es más
    riesgo pone el límite inferior en su onset, y una donde más flexión es más riesgo pone el superior.
    Así los análisis viejos conservan los umbrales con que se puntuaron.
    """

    def read(self, assessment: movement_pb2.RiskAssessment) -> KneeReading:
        signals = [
            signal
            for pattern in assessment.patterns
            for signal in pattern.signals
            if signal.joint == movement_pb2.JOINT_ANGLE_KNEE_FLEXION
        ]
        # Todas las señales de rodilla miden el mismo pico por repetición: cualquier medida sirve
        measured = next((signal.measured for signal in signals if signal.HasField("measured")), None)
        lows = [s.onset_degrees for s in signals if s.direction == movement_pb2.RISK_DIRECTION_LOWER_IS_RISKIER]
        highs = [s.onset_degrees for s in signals if s.direction == movement_pb2.RISK_DIRECTION_HIGHER_IS_RISKIER]
        target = None
        if lows or highs:
            target = movement_pb2.AngleRange()
            if lows:
                target.low_degrees = max(lows)
            if highs:
                target.high_degrees = min(highs)
        return KneeReading(measured.median_degrees if measured else None, target)
