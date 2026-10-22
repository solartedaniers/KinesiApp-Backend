from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.rpc.error_status import STATUS_BY_REASON, reason_name


def test_every_contract_reason_has_a_status_code() -> None:
    # Si el contrato agrega un motivo, este test obliga a decidir su status code
    reasons = {value for value in ErrorReason.values() if value != ErrorReason.ERROR_REASON_UNSPECIFIED}

    assert set(STATUS_BY_REASON) == reasons


def test_reason_name_drops_the_enum_prefix() -> None:
    assert reason_name(ErrorReason.ERROR_REASON_EMAIL_ALREADY_REGISTERED) == "EMAIL_ALREADY_REGISTERED"
