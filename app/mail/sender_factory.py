from app.mail.email_sender import EmailSender, UnconfiguredEmailSender
from app.mail.resend_email_sender import ResendEmailSender
from app.settings.mail import MailSettings


def build_email_sender(config: MailSettings) -> EmailSender:
    if config.RESEND_API_KEY is None or not config.RESEND_API_KEY.get_secret_value():
        return UnconfiguredEmailSender()
    return ResendEmailSender(
        api_key=config.RESEND_API_KEY.get_secret_value(),
        from_email=config.RESEND_FROM_EMAIL,
        timeout_seconds=config.RESEND_TIMEOUT_SECONDS,
    )
