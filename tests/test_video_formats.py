import pytest

from app.storage.video_formats import looks_like_video

MP4 = b"\x00\x00\x00\x20ftypisom"
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81"
AVI = b"RIFF\x00\x10\x00\x00AVI "


@pytest.mark.parametrize("head", [MP4, WEBM, AVI], ids=["mp4", "webm", "avi"])
def test_common_containers_are_recognized(head: bytes) -> None:
    assert looks_like_video(head)


@pytest.mark.parametrize("head", [b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d", b"RIFF\x00\x10\x00\x00WEBP", b""], ids=["png", "webp", "empty"])
def test_other_files_are_not_videos(head: bytes) -> None:
    assert not looks_like_video(head)
