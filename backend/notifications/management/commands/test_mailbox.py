"""
Check that email from Conformiti reaches people, whatever EMAIL_PROVIDER is.

    python manage.py test_mailbox                 # mailbox only: sign in, send nothing
    python manage.py test_mailbox --to you@x.com  # send a sample review reminder

With EMAIL_PROVIDER=mailbox the MAILBOX_* account is signed in to first (IMAP
or POP3), which proves the credentials before anything is sent. The other
providers (smtp, ses, console) have no mailbox to sign in to, so they need
--to.

The test message is a sample review reminder, sent through
notifications.email_service with the template and transport the reminder scan
uses, so a message that arrives shows real reminders will. With console it is
printed here, not delivered.
"""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.utils import timezone


class Command(BaseCommand):
    help = ("Send a sample review reminder through EMAIL_PROVIDER (any provider); "
            "with mailbox, sign in over IMAP/POP3 first.")

    def add_arguments(self, parser):
        parser.add_argument("--to", help="Send a sample review reminder to this address.")

    def handle(self, *args, **options):
        provider = settings.EMAIL_PROVIDER
        to = (options.get("to") or "").strip()
        if to:
            try:
                validate_email(to)
            except ValidationError:
                raise CommandError(f"--to {to!r} is not an email address.")

        if provider == "mailbox":
            self._verify_mailbox()
        elif not to:
            raise CommandError(
                f"EMAIL_PROVIDER is '{provider}', which has no mailbox to sign in to. "
                "Pass --to you@example.com to send a test message through it."
            )

        if not to:
            self.stdout.write("No --to given; skipping test send. Verification passed.")
            return

        self.stdout.write(f"Sending a sample review reminder to {to} {self._route(provider)} ...")
        from notifications.email_service import send_templated_email

        days = 30
        context = {
            "document": {
                "name": "Sample document (a test from manage.py test_mailbox, no action needed)",
                "get_review_cadence_display": "Annual",
                "next_review_date": timezone.localdate() + timedelta(days=days),
            },
            "days": days,
            "overdue": False,
            "owner_name": "administrator",
            "folder_path": "Test message",
        }
        try:
            send_templated_email("[Test] Sample review reminder from Conformiti",
                                 "review_reminder", context, [to])
        except Exception as exc:  # noqa: BLE001 - surface the real error to the operator
            raise CommandError(f"Test send failed: {exc}")
        if provider == "console":
            self.stdout.write(self.style.SUCCESS(
                f"Test email to {to} printed above. EMAIL_PROVIDER=console delivers nothing."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Test email sent to {to}."))

    def _verify_mailbox(self):
        if not settings.MAILBOX_HOST or not settings.MAILBOX_USERNAME:
            raise CommandError("MAILBOX_HOST and MAILBOX_USERNAME must be set.")

        from notifications.mailbox import verify_mailbox

        self.stdout.write(f"Connecting via {settings.MAILBOX_PROTOCOL.upper()} ...")
        try:
            status = verify_mailbox()
        except Exception as exc:  # noqa: BLE001 - surface the real error to the operator
            raise CommandError(f"Mailbox verification failed: {exc}")
        self.stdout.write(self.style.SUCCESS(status))

    @staticmethod
    def _route(provider):
        """Where send_templated_email hands the message for ``provider``."""
        if provider == "mailbox":
            return f"over SMTP ({settings.MAILBOX_SMTP_HOST or settings.MAILBOX_HOST})"
        if provider == "ses":
            return f"through Amazon SES ({settings.AWS_SES_REGION})"
        if provider == "smtp":
            return f"over SMTP ({settings.EMAIL_HOST}:{settings.EMAIL_PORT})"
        if provider == "console":
            return "to the console"
        return f"through Django's email backend ({settings.EMAIL_BACKEND})"
