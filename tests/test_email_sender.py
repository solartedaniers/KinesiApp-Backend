import pytest

from app.core.email import SmtpEmailSender


def _fake_smtp(calls, sent):
    class FakeSmtp:
        def __init__(self, *args, **kwargs): calls.append(type(self).__name__)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def close(self): ...
        def ehlo(self): calls.append("ehlo")
        def has_extn(self, name): return True
        def starttls(self, context): calls.append("starttls")
        def auth_plain(self): ...
        def auth(self, mechanism, authobject): calls.append("auth"); sent["login"] = self.user

        def send_message(self, message, from_addr, to_addrs):
            sent.update(header=message["From"], envelope=from_addr, to=to_addrs)
            return {}

    return FakeSmtp


@pytest.mark.parametrize(
    ("port", "use_ssl", "expected_calls"),
    [
        (587, False, ["SMTP", "ehlo", "starttls", "ehlo", "auth"]),
        (465, False, ["SMTP_SSL", "ehlo", "auth"]),  # 465 fuerza SSL aunque SMTP_USE_TLS=true
    ],
)
def test_sender_connection_mode_and_authenticated_from(monkeypatch, port, use_ssl, expected_calls):
    calls, sent = [], {}
    plain = _fake_smtp(calls, sent)
    monkeypatch.setattr("app.core.email.smtplib.SMTP", type("SMTP", (plain,), {}))
    monkeypatch.setattr("app.core.email.smtplib.SMTP_SSL", type("SMTP_SSL", (plain,), {}))

    sender = SmtpEmailSender("smtp.gmail.com", port, "app@gmail.com", "pw", "KinesiApp", True, use_ssl, 5)
    sender.send("patient@outlook.com", "Hola", "Cuerpo")

    assert calls == expected_calls
    assert sent["login"] == sent["envelope"] == "app@gmail.com"
    assert sent["header"] == "KinesiApp <app@gmail.com>"
    assert sent["to"] == ["patient@outlook.com"]
