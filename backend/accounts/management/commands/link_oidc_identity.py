"""
Link (or unlink) a single sign-on identity to a local account by hand.

    python manage.py link_oidc_identity mia 00u1abcd --email mia@example.com
    python manage.py link_oidc_identity mia 00u1abcd --issuer https://login.example.com
    python manage.py link_oidc_identity mia --unlink

This is how an administrator pre-links accounts before turning SSO on, and
how a superuser gets an SSO identity at all: the automatic email match never
links privileged accounts, so linking one is an explicit, audited act here.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import OidcIdentity
from accounts.oidc import config
from audit.models import AuditLog


class Command(BaseCommand):
    help = "Link an OpenID Connect identity (issuer + subject) to a local user."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("subject", nargs="?", help="The provider's stable subject id (sub).")
        parser.add_argument("--issuer", default="", help="Defaults to OIDC_ISSUER.")
        parser.add_argument("--email", default="", help="Email the provider reports, for the record.")
        parser.add_argument("--allow-privileged", action="store_true",
                            help="Required to link a superuser or staff account.")
        parser.add_argument("--unlink", action="store_true", help="Remove every identity on the account.")

    def handle(self, *args, **opts):
        user = get_user_model().objects.filter(username=opts["username"]).first()
        if user is None:
            raise CommandError(f"No user named {opts['username']!r}.")
        if opts["unlink"]:
            n, _ = OidcIdentity.objects.filter(user=user).delete()
            AuditLog.objects.create(user=None, action="delete", object_type="auth",
                                    object_id=str(user.pk),
                                    detail=f"sso identities unlinked from {user.get_username()} (CLI)")
            self.stdout.write(self.style.SUCCESS(f"Removed {n} identity record(s) from {user.get_username()}."))
            return
        subject = (opts["subject"] or "").strip()
        if not subject:
            raise CommandError("A subject id is required (or pass --unlink).")
        issuer = (opts["issuer"] or config().issuer).strip().rstrip("/")
        if not issuer:
            raise CommandError("No issuer: pass --issuer or set OIDC_ISSUER.")
        privileged = user.is_superuser or user.is_staff or user.can_manage_users
        if privileged and not opts["allow_privileged"]:
            raise CommandError(
                f"{user.get_username()} is a superuser/staff account. Linking it lets the identity "
                "provider's administrators sign in as your administrator; pass --allow-privileged "
                "if that is what you intend."
            )
        clash = OidcIdentity.objects.filter(issuer=issuer, subject=subject).exclude(user=user).first()
        if clash:
            raise CommandError(f"That identity is already linked to {clash.user.get_username()}.")
        identity, created = OidcIdentity.objects.update_or_create(
            issuer=issuer, subject=subject,
            defaults={"user": user, "email": (opts["email"] or user.email or "").lower()[:254],
                      "privileged_ok": bool(opts["allow_privileged"])},
        )
        AuditLog.objects.create(user=None, action="create" if created else "update", object_type="auth",
                                object_id=str(user.pk),
                                detail=f"sso identity {'linked' if created else 'updated'} for "
                                       f"{user.get_username()} at {issuer} (CLI)"[:255])
        self.stdout.write(self.style.SUCCESS(
            f"{'Linked' if created else 'Updated'} {issuer} / {subject} -> {user.get_username()}."))
