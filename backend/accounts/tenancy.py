"""Tenant isolation: a TenantModel queryset is pinned to the active workspace. With none active it is unfiltered,
right for migrations and jobs, wrong for a request, so a person with no workspace is refused (403)."""
import contextvars
import logging
from contextlib import contextmanager

from django.contrib.auth.models import UserManager
from django.db import models
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

DEFAULT_SLUG = "default"
HEADER = "HTTP_X_WORKSPACE"


class UnscopedRead(RuntimeError):
    """A queryset that cannot be scoped fails with this instead of returning every organisation's rows."""

# Holds an int (workspace id), a _RequestResolver, or None.
_active = contextvars.ContextVar("conformiti.workspace", default=None)


class NoActiveWorkspace(RuntimeError):
    """Saving a tenant row with nothing to tell which organisation owns it."""


def current_id():
    """Id of the active workspace, or None when nothing is active."""
    value = _active.get()
    if value is None or isinstance(value, int):
        return value
    return value.resolve()


def current():
    wid = current_id()
    if wid is None:
        return None
    from .models import Workspace

    return Workspace.objects.filter(pk=wid).first()


def activate(workspace):
    """Make ``workspace`` (an instance or id) active until further notice. Outside the test runner use scoped()."""
    _active.set(_id_of(workspace))


def deactivate():
    _active.set(None)


@contextmanager
def scoped(workspace):
    """Run the block with ``workspace`` active (``None`` = unscoped)."""
    token = _active.set(_id_of(workspace))
    try:
        yield
    finally:
        _active.reset(token)


def unscoped():
    """Run the block with no workspace active, so every organisation's rows show. Only for platform-level views."""
    return scoped(None)


def for_each_workspace(include_inactive=False):
    """Yield each workspace with it active, for jobs that walk them all."""
    from .models import Workspace

    qs = Workspace.objects.order_by("pk")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    for ws in qs:
        with scoped(ws):
            yield ws


def default_workspace():
    from .models import Workspace

    ws, _ = Workspace.objects.get_or_create(slug=DEFAULT_SLUG, defaults={"name": "Default"})
    return ws


def organisation_name():
    from django.conf import settings

    from .models import Workspace

    ws = current()
    if ws is not None and Workspace.objects.count() > 1:
        return ws.name
    return (getattr(settings, "ORGANISATION_NAME", "") or "").strip()


def _id_of(workspace):
    if workspace is None:
        return None
    return workspace if isinstance(workspace, int) else workspace.pk


def workspace_id_for(user, wanted=None):
    """Which workspace ``user`` works in. ``wanted`` (the X-Workspace header) is honoured for a superuser only.
    Raises PermissionDenied when the account has nowhere to go."""
    from .models import Workspace

    # Archived workspaces are also refused at sign-in and by the authentication class. Only a workspace already on the
    # instance is read here, so a request costs no extra query.
    cached = user._state.fields_cache.get("workspace") if user.workspace_id else None
    if cached is not None and not cached.is_active and not user.is_superuser:
        raise PermissionDenied("This workspace is archived.")
    if wanted and user.is_superuser:
        ws = Workspace.objects.filter(slug=wanted).first()
        if ws is None and str(wanted).isdigit():
            ws = Workspace.objects.filter(pk=int(wanted)).first()
        if ws is None:
            raise PermissionDenied(f"No workspace named {wanted!r}.")
        if not ws.is_active:
            raise PermissionDenied(f"Workspace {ws.name!r} is archived.")
        return ws.pk
    if user.workspace_id:
        return user.workspace_id
    if user.is_superuser:
        first = Workspace.objects.filter(is_active=True).order_by("pk").values_list("pk", flat=True).first()
        if first:
            return first
    raise PermissionDenied("This account is not attached to a workspace.")


class _RequestResolver:
    """Resolves and caches the request's workspace on the first tenant query. Re-entrant: resolving the user runs a
    User query, which must stay unscoped."""

    __slots__ = ("request", "_busy")

    def __init__(self, request):
        self.request = request
        self._busy = False

    def resolve(self):
        cached = getattr(self.request, "_workspace_id", None)
        if cached:
            return cached
        if self._busy:
            return None
        self._busy = True
        try:
            user = getattr(self.request, "user", None)
            if user is None or not user.is_authenticated:
                return None
            wid = workspace_id_for(user, self.request.META.get(HEADER))
            self.request._workspace_id = wid
            return wid
        finally:
            self._busy = False


class WorkspaceMiddleware:
    """A resolver per request, put back afterwards; lazy because DRF authenticates after middleware. Must sit inside
    AuthenticationMiddleware and outside AuditLogMiddleware, which writes a tenant row."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _active.set(_RequestResolver(request))
        try:
            return self.get_response(request)
        finally:
            _active.reset(token)


def request_workspace(request):
    """The workspace a request resolved to, as an instance (or None)."""
    from .models import Workspace

    wid = current_id()
    return Workspace.objects.filter(pk=wid).first() if wid else None


class ActiveWorkspace(models.Expression):
    """The active workspace id, read when the query compiles rather than when it is built: a pinned queryset never
    shows another workspace's rows, and shows none when nothing is active."""

    def __init__(self):
        super().__init__(output_field=models.IntegerField())

    def as_sql(self, compiler, connection):
        return "%s", [current_id()]

    def __repr__(self):
        return "ActiveWorkspace()"


class TenantQuerySet(models.QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant = False  # carries the workspace condition already

    def _clone(self):
        clone = super()._clone()
        clone._tenant = self._tenant
        return clone

    def _chain(self):
        return super()._chain()._pin()

    def _pin(self):
        if self._tenant:
            return self
        if current_id() is None:
            return self  # nothing active: migrations, createsuperuser, jobs that walk every workspace
        if self.query.is_sliced or self.query.combinator:
            # A sliced or UNIONed query cannot take the condition, and returning it as it is would hand back every
            # organisation's rows. Managers pin before any slice, so this queryset was built with nothing active.
            raise UnscopedRead(
                "This queryset was built with no workspace active and cannot be "
                "scoped now that one is. Build it inside the workspace, or read "
                "it deliberately inside tenancy.unscoped()."
            )
        self._tenant = True
        self.query.add_q(models.Q(workspace_id=ActiveWorkspace()))
        return self

    # _chain() pins derived querysets; these are the other ways one reaches the database, built in one scope and
    # read in another with nothing derived in between.
    def _fetch_all(self):
        self._pin()
        super()._fetch_all()

    def count(self):
        self._pin()
        return super().count()

    def exists(self):
        self._pin()
        return super().exists()

    def aggregate(self, *args, **kwargs):
        self._pin()
        return super().aggregate(*args, **kwargs)

    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            obj.assign_workspace()
        return super().bulk_create(objs, *args, **kwargs)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    def get_queryset(self):
        return super().get_queryset()._pin()


class TenantUserManager(UserManager.from_queryset(TenantQuerySet)):
    def get_queryset(self):
        return super().get_queryset()._pin()

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Held to AUTH_PASSWORD_VALIDATORS even for --noinput, which stock Django exempts.
        if password is not None:
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError

            try:
                validate_password(password, self.model(username=username, email=email or ""))
            except ValidationError as err:
                raise ValidationError(
                    "Superuser not created. The password must pass this installation's "
                    "password policy, with no bypass. " + " ".join(err.messages)
                ) from err
        # With no workspace the account could sign in to /admin/ and then be treated as anonymous: the session's user
        # lookup is pinned to the request's workspace, which matches no row without one.
        if current_id() is None and "workspace" not in extra_fields and "workspace_id" not in extra_fields:
            from .models import Workspace

            first = (Workspace.objects.filter(is_active=True).order_by("pk")
                     .values_list("pk", flat=True).first())
            extra_fields["workspace_id"] = first or default_workspace().pk
        return super().create_superuser(username, email, password, **extra_fields)


class TenantModel(models.Model):
    """Base of org-owned models. ``tenant_parent`` names the foreign key a new row inherits its workspace from."""

    tenant_parent = None

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="+", editable=False,
    )

    objects = TenantManager()

    class Meta:
        abstract = True

    def assign_workspace(self):
        if self.workspace_id is not None:
            return self.workspace_id
        wid = None
        if self.tenant_parent and getattr(self, f"{self.tenant_parent}_id", None):
            wid = getattr(self, self.tenant_parent).workspace_id
        if wid is None:
            wid = current_id()
        if wid is None and not self._meta.get_field("workspace").null:
            raise NoActiveWorkspace(
                f"{type(self).__name__} saved with no workspace and none active; "
                "wrap the caller in tenancy.scoped(workspace)."
            )
        self.workspace_id = wid
        return wid

    def save(self, *args, **kwargs):
        self.assign_workspace()
        super().save(*args, **kwargs)


class CurrentWorkspaceDefault:
    """For ``serializers.HiddenField(default=CurrentWorkspaceDefault())``: a per-workspace unique constraint then
    validates as 400 instead of failing as an IntegrityError."""

    requires_context = True

    def __call__(self, serializer_field):
        wid = current_id()
        if wid is None:
            raise PermissionDenied("No workspace is active.")
        return current()

    def __repr__(self):
        return "CurrentWorkspaceDefault()"


def workspace_option(parser):
    parser.add_argument(
        "--workspace", default=DEFAULT_SLUG, metavar="SLUG",
        help=f"Which workspace to act on (default: {DEFAULT_SLUG}).",
    )


def from_option(opts):
    """Resolve ``--workspace`` to an instance, or raise CommandError."""
    from django.core.management.base import CommandError

    from .models import Workspace

    slug = opts.get("workspace") or DEFAULT_SLUG
    ws = Workspace.objects.filter(slug=slug).first()
    if ws is None:
        known = ", ".join(Workspace.objects.values_list("slug", flat=True)) or "none"
        raise CommandError(f"No workspace {slug!r} (known: {known}).")
    return ws
