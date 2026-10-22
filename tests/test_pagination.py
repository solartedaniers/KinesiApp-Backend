import pytest
from pydantic import ValidationError

from app.core.pagination import PageRules, encode_page_token

RULES = PageRules(default_size=20, max_size=100)


def test_page_size_uses_the_default_and_never_passes_the_maximum() -> None:
    assert RULES.parse(0, "").limit == 20
    assert RULES.parse(7, "").limit == 7
    assert RULES.parse(5000, "").limit == 100


def test_page_token_round_trips_the_last_id() -> None:
    assert RULES.parse(0, "").after_id == 0
    assert RULES.parse(0, encode_page_token(42)).after_id == 42


@pytest.mark.parametrize("token", ["no-es-base64!", encode_page_token(0), "YWJj"])
def test_invalid_page_token_is_reported_on_its_field(token: str) -> None:
    with pytest.raises(ValidationError) as raised:
        RULES.parse(0, token)

    assert raised.value.errors()[0]["loc"] == ("page_token",)


def test_negative_page_size_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RULES.parse(-1, "")
