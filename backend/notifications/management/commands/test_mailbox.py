"""
Verify the configured mailbox and (optionally) send a test message.

    python manage.py test_mailbox                 # connect + verify only
    python manage.py test_mailbox --to you@x.com  # verify, then send a test email

Requires EMAIL_PROVIDER=mailbox with the MAILBOX_* settings populated. Useful as
a first smoke test before relying on the account for review reminders.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify the IMAP/POP3 + SMTP mailbox and optionally send a test email."

    def add_arguments(self, parser):
        parser.add_argument("--to", help="Send a test email to this address after verifying.")

    def handle(self, *args, **options):
        if settings.EMAIL_PROVIDER != "mailbox":
            raise CommandError(
                f"EMAIL_PROVIDER is '{settings.EMAIL_PROVIDER}', not 'mailbox'. "
                "Set EMAIL_PROVIDER=mailbox and the MAILBOX_* settings first."
            )
        if not settings.MAILBOX_HOST or not settings.MAILBOX_USERNAME:
            raise CommandError("MAILBOX_HOST and MAILBOX_USERNAME must be set.")

        from notifications.mailbox import verify_mailbox, send_mailbox_email

        self.stdout.write(f"Connecting via {settings.MAILBOX_PROTOCOL.upper()} …")
        try:
            status = verify_mailbox()
        except Exception as exc:  # noqa: BLE001 - surface the real error to the operator
            raise CommandError(f"Mailbox verification failed: {exc}")
        self.stdout.write(self.style.SUCCESS(status))

        to = options.get("to")
        if not to:
            self.stdout.write("No --to given; skipping test send. Verification passed.")
            return

        self.stdout.write(f"Sending test email to {to} via SMTP "
                          f"({settings.MAILBOX_SMTP_HOST or settings.MAILBOX_HOST}) …")
        html = (
            "<p>This is a test message from Conformiti's mailbox mailer.</p>"
            "<p>If you received this, review reminders will reach document owners.</p>"
        )
        text = ("This is a test message from Conformiti's mailbox mailer. "
                "If you received this, review reminders will reach document owners.")
        try:
            send_mailbox_email("Conformiti — mailbox test", html, text, [to])
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Test send failed: {exc}")
        self.stdout.write(self.style.SUCCESS(f"Test email sent to {to}."))
