"""Provider-agnostic mail: ``ses`` and ``mailbox`` have their own senders; every other EMAIL_PROVIDER (smtp, console)
goes through Django's email backend."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_templated_email(subject, template, context, recipients):
    recipients = [r for r in dict.fromkeys(recipients) if r]
    if not recipients:
        logger.warning("No recipients for '%s'; skipping.", subject)
        return False

    html_body = render_to_string(f"emails/{template}.html", context)
    text_body = render_to_string(f"emails/{template}.txt", context)

    if settings.EMAIL_PROVIDER == "ses":
        from .ses import send_ses_email
        send_ses_email(subject, html_body, text_body, recipients)
    elif settings.EMAIL_PROVIDER == "mailbox":
        from .mailbox import send_mailbox_email
        send_mailbox_email(subject, html_body, text_body, recipients)
    else:
        msg = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, recipients)
        msg.attach_alternative(html_body, "text/html")
        msg.send()

    logger.info("Sent '%s' to %s via %s", subject, recipients, settings.EMAIL_PROVIDER)
    return True
