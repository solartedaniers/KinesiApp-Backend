import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("copy_dev_accounts", Path(__file__).resolve().parents[1] / "scripts" / "copy_dev_accounts.py")
copy_dev_accounts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(copy_dev_accounts)

ENDPOINT = "https://storage.example"
BUCKETS = copy_dev_accounts.Buckets(ENDPOINT, "dev-images", "dev-videos", "prod-images", "prod-videos")
CREATED = datetime(2026, 10, 3, tzinfo=timezone.utc)


def account(account_id: int, password_hash: str = "hash-a", created_at: datetime = CREATED) -> dict:
    return {"id": account_id, "email": "coach@example.com", "hashed_password": password_hash, "created_at": created_at}


def test_a_new_email_is_inserted():
    assert copy_dev_accounts.decide_account(account(1), None, set(), set()).action == "insert"


def test_an_account_already_copied_is_kept_with_its_target_id():
    decision = copy_dev_accounts.decide_account(account(4), account(9), set(), set())
    assert (decision.action, decision.target_id) == ("keep", 9)


def test_an_existing_email_is_never_overwritten_without_permission():
    with pytest.raises(copy_dev_accounts.CopyAborted):
        copy_dev_accounts.decide_account(account(4), account(2, "hash-b"), set(), set())


@pytest.mark.parametrize("flag, action", [("update", "update"), ("replace", "replace")])
def test_an_existing_email_is_updated_or_replaced_when_asked(flag, action):
    allowed = {"coach@example.com"}
    decision = copy_dev_accounts.decide_account(
        account(4), account(2, "hash-b"), allowed if flag == "update" else set(), allowed if flag == "replace" else set()
    )
    assert (decision.action, decision.target_id) == (action, 2)


def test_a_video_moves_to_the_new_athlete_folder_of_the_target_bucket():
    url, copy = BUCKETS.rewrite(f"{ENDPOINT}/dev-videos/videos/2/abc", athlete_id=7)
    assert url == f"{ENDPOINT}/prod-videos/videos/7/abc"
    assert copy == ("dev-videos", "videos/2/abc", "prod-videos", "videos/7/abc")


def test_an_avatar_keeps_its_key():
    url, copy = BUCKETS.rewrite(f"{ENDPOINT}/dev-images/avatars/x.jpg")
    assert url == f"{ENDPOINT}/prod-images/avatars/x.jpg"
    assert copy == ("dev-images", "avatars/x.jpg", "prod-images", "avatars/x.jpg")


def test_a_url_outside_the_source_buckets_aborts():
    with pytest.raises(copy_dev_accounts.CopyAborted):
        BUCKETS.rewrite(f"{ENDPOINT}/videos/old.mp4")


def test_no_file_means_no_copy():
    assert BUCKETS.rewrite(None) == (None, None)
