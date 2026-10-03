"""ResendEmailSender, su armado desde Settings y la verificación DNS del dominio, sin red."""
import dns.exception
import dns.resolver
import pytest
import resend
from pydantic import SecretStr
from resend.exceptions import ResendError

from app.core.config import settings
from app.mail.email_sender import EmailDeliveryError, UnconfiguredEmailSender
from app.mail.resend_email_sender import ResendEmailSender
from app.services import email_domain_checker
from app.services.email_domain_checker import EmailDomainChecker
from app.services.email_factory import build_email_sender


def _sender(monkeypatch, outcome):
    calls = []

    def send(params):
        calls.append(params)
        if isinstance(outcome, Exception):
            raise outcome
        return {"id": "email-id"}

    monkeypatch.setattr(resend.Emails, "send", send)
    return ResendEmailSender(api_key="re_test", from_email="KinesiApp <no-reply@kinesi.app>", timeout_seconds=5), calls


def test_sends_plain_text_from_the_configured_sender(monkeypatch):
    sender, calls = _sender(monkeypatch, None)
    sender.send("ana@example.com", "Asunto", "Cuerpo")
    assert calls == [
        {"from": "KinesiApp <no-reply@kinesi.app>", "to": ["ana@example.com"], "subject": "Asunto", "text": "Cuerpo"}
    ]
    assert resend.api_key == "re_test"


def test_provider_and_network_errors_become_email_delivery_errors(monkeypatch):
    # El SDK envuelve también los errores de red (HttpClientError) en ResendError
    sender, _ = _sender(monkeypatch, ResendError(500, "HttpClientError", "Request failed", "Retry"))
    with pytest.raises(EmailDeliveryError):
        sender.send("ana@example.com", "Asunto", "Cuerpo")


def test_factory_without_api_key_returns_a_sender_that_fails_explicitly(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", SecretStr(""))
    sender = build_email_sender(settings)
    assert isinstance(sender, UnconfiguredEmailSender)
    with pytest.raises(EmailDeliveryError, match="RESEND_API_KEY"):
        sender.send("ana@example.com", "Asunto", "Cuerpo")

    monkeypatch.setattr(settings, "RESEND_API_KEY", SecretStr("re_test"))
    assert isinstance(build_email_sender(settings), ResendEmailSender)


class _FakeAnswer(list):
    def __init__(self, records, rrset=True):
        super().__init__(records)
        self.rrset = records if rrset else None


class _MxRecord:
    def __init__(self, exchange: str, preference: int = 10) -> None:
        self.exchange = dns.name.from_text(exchange)
        self.preference = preference


class _FakeResolver:
    """Resolver que responde lo que el test indique por tipo de registro; nunca sale a la red."""

    def __init__(self, answers):
        self._answers = answers
        self.lifetime = None

    def resolve(self, domain, record_type, **kwargs):
        answer = self._answers.get(record_type, dns.resolver.NoAnswer())
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def resolver(monkeypatch):
    def install(answers):
        fake = _FakeResolver(answers)
        monkeypatch.setattr(dns.resolver, "get_default_resolver", lambda: fake)
        return fake

    return install


def test_domain_with_mx_is_deliverable(resolver):
    resolver({"MX": _FakeAnswer([_MxRecord("mail.example.com.")]), "TXT": _FakeAnswer([])})
    assert EmailDomainChecker(timeout_seconds=1).is_deliverable("ana@example.com")


def test_nonexistent_domain_is_rejected(resolver):
    resolver({"MX": dns.resolver.NXDOMAIN()})
    assert not EmailDomainChecker(timeout_seconds=1).is_deliverable("ana@dominio-inventado.com")


def test_domain_without_mail_records_is_rejected(resolver):
    # Sin MX, sin A y sin AAAA: no hay dónde entregar el correo
    resolver({})
    assert not EmailDomainChecker(timeout_seconds=1).is_deliverable("ana@sin-correo.com")


@pytest.mark.parametrize(
    "transient",
    [dns.resolver.LifetimeTimeout(timeout=1, errors={}), dns.resolver.NoNameservers(), OSError("network down")],
)
def test_transient_dns_failures_accept_the_format_and_warn(resolver, caplog, transient):
    resolver({"MX": transient})
    with caplog.at_level("WARNING", logger=email_domain_checker.__name__):
        assert EmailDomainChecker(timeout_seconds=1).is_deliverable("ana@example.com")
    assert "accepting format only" in caplog.text


def test_missing_resolver_configuration_accepts_the_format_and_warns(monkeypatch, caplog):
    def no_configuration():
        raise dns.resolver.NoResolverConfiguration()

    monkeypatch.setattr(dns.resolver, "get_default_resolver", no_configuration)
    with caplog.at_level("WARNING", logger=email_domain_checker.__name__):
        assert EmailDomainChecker(timeout_seconds=1).is_deliverable("ana@example.com")
    assert "accepting format only" in caplog.text
