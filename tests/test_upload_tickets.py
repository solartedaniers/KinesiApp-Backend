import pytest

from app.core.domain_error import DomainError
from app.settings.auth import AuthSettings
from app.storage.upload_tickets import UploadPurpose, UploadTicket, UploadTicketService

SETTINGS = AuthSettings(_env_file=None, JWT_SECRET_KEY="upload-ticket-test-secret", OTP_EXPIRE_MINUTES=10)
TICKET = UploadTicket(7, UploadPurpose.AVATAR, "avatars/abc.png", "image/png", 2048)


def test_ticket_carries_what_was_authorized() -> None:
    tickets = UploadTicketService(SETTINGS, lifetime_seconds=60)

    assert tickets.verify(tickets.issue(TICKET), 7, UploadPurpose.AVATAR) == TICKET


@pytest.mark.parametrize(
    "upload_id, owner_id, lifetime",
    [
        (None, 8, 60),
        ("not-a-ticket", 7, 60),
        (None, 7, -1),
    ],
    ids=["other-owner", "garbage", "expired"],
)
def test_foreign_garbage_or_expired_tickets_are_not_found(upload_id, owner_id, lifetime) -> None:
    tickets = UploadTicketService(SETTINGS, lifetime_seconds=lifetime)

    with pytest.raises(DomainError) as raised:
        tickets.verify(upload_id or tickets.issue(TICKET), owner_id, UploadPurpose.AVATAR)

    assert raised.value.message == "The upload does not exist or has expired"
