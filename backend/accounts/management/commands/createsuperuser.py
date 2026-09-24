"""
``manage.py createsuperuser`` without Django's "Bypass password validation"
question.

Stock Django offers, when a typed password fails AUTH_PASSWORD_VALIDATORS,
to create the account anyway. This installation's policy has no bypass
(TenantUserManager.create_superuser refuses such a password whatever the
answer), so a yes ended the command with an error and threw away the
username and email already typed. Here the question is never put: the
command says the policy has no bypass and asks for another password, the way
Django's own loop does after a no.

Everything else is Django's command, unchanged: ``--noinput`` with
DJANGO_SUPERUSER_* works as before, and the policy is still applied by the
manager. accounts comes before django.contrib.auth in INSTALLED_APPS so that
Django finds this command rather than its own.
"""
import builtins

from django.contrib.auth.management.commands import createsuperuser as stock

# The start of the question Django asks through a bare input() call.
BYPASS_QUESTION = "Bypass password validation"
NO_BYPASS = "This installation's password policy has no bypass. Enter a different password."


class Command(stock.Command):
    def handle(self, *args, **options):
        def ask(prompt=""):
            if str(prompt).startswith(BYPASS_QUESTION):
                self.stderr.write(NO_BYPASS)
                return "n"  # Django's loop then asks for the password again
            return builtins.input(prompt)

        # Django's module calls input() by its global name; shadow it for the
        # length of this command only.
        previous = stock.__dict__.get("input")
        stock.input = ask
        try:
            return super().handle(*args, **options)
        finally:
            if previous is None:
                del stock.input
            else:
                stock.input = previous
