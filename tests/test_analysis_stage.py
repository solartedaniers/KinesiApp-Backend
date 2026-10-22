from kinesiapp.common.v1 import movement_pb2

from app.models.jump_analysis import AnalysisStage


def test_persisted_stages_match_the_contract() -> None:
    contract = {
        name.removeprefix("ANALYSIS_STAGE_")
        for name in movement_pb2.AnalysisStage.keys()
        if name != "ANALYSIS_STAGE_UNSPECIFIED"
    }

    assert {stage.name for stage in AnalysisStage} == contract
