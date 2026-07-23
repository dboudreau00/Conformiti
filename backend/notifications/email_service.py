"""Provider-agnostic email sending.

EMAIL_PROVIDER selects the transport:
  * ``ses``     -> Amazon SES (boto3)
  * ``mailbox`` -> a standard IMAP/POP3 + SMTP mailbox account (notifications.mailbox)
  * ``smtp``    -> Django's SMTP backend
  * ``console`` -> print to stdout (default in DEBUG)
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_templated_email(subject, template, context, recipients):
    """Render <template>.html/.txt from templates/emails and send to recipients."""
    recipients = [r for r in dict.fromkeys(recipients) if r]  # dedupe, drop blanks
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
