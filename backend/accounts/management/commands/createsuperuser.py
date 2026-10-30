"""``createsuperuser`` without Django's bypass-password-validation question: the policy has no bypass.
Found instead of Django's command because accounts precedes django.contrib.auth in INSTALLED_APPS."""
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
