"""Compruebo que ni subiendo el log a DEBUG se registran las URLs firmadas de las librerías HTTP."""

import logging

import pytest

from app.rpc.server import QUIET_HTTP_LOGGERS, configure_logging

SIGNED_URL = "https://storage.neon.test/videos/a.mp4?X-Amz-Signature=deadbeef"


@pytest.mark.parametrize("name", QUIET_HTTP_LOGGERS)
def test_http_libraries_do_not_log_requests_even_in_debug(name: str, caplog: pytest.LogCaptureFixture) -> None:
    configure_logging(logging.DEBUG)
    caplog.set_level(logging.DEBUG)

    logging.getLogger(f"{name}.connectionpool").debug('"GET %s HTTP/1.1" 200', SIGNED_URL)
    logging.getLogger(name).info("HTTP Request: GET %s", SIGNED_URL)

    assert "X-Amz-Signature" not in caplog.text
