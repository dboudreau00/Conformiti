"""Workspaces: one installation serving several organisations, each seeing
only its own.

How it works
------------
* ``accounts.Workspace`` is the tenant. Every model an organisation owns
  inherits :class:`TenantModel`, which adds a ``workspace`` foreign key and a
  manager whose querysets carry ``WHERE workspace_id = <active>`` whenever a
  workspace is *active* on the current thread of execution.
* The active workspace lives in a context variable. For an API request,
  :class:`WorkspaceMiddleware` installs a resolver that reads the workspace
  off the authenticated person the first time a tenant query runs (DRF
  authenticates inside the view, after middleware, so it has to be lazy);
  a superuser may name another workspace in an ``X-Workspace`` header. The
  variable is restored when the request ends, so nothing leaks between
  requests on a reused worker. Tasks and commands activate one explicitly
  with :func:`scoped` and walk them all with :func:`for_each_workspace`.
* A row saved without a workspace takes it from its declared parent
  (``tenant_parent = "folder"``) or from the active workspace, and refuses
  otherwise: a background job cannot file something into the wrong
  organisation by omission.
* No active workspace means no filter. That is right for migrations,
  ``createsuperuser`` and jobs that walk every workspace, and wrong for a
  request, which is why a person with no workspace is refused (403) and why
  the escape hatch is spelled :func:`unscoped` and used in three places.

The filter is added the first time a queryset is chained with a workspace
active, so a queryset built at import time (``queryset = Model.objects.all()``
on a viewset, the ``queryset=`` of a serializer field) is scoped the moment
DRF calls ``.all()`` on it inside a request. The condition compares against
the workspace active *when the query runs* (:class:`ActiveWorkspace`), so a
pinned queryset never shows another workspace's rows, and shows none when
nothing is active.
"""
import contextvars
import logging
from contextlib import contextmanager

from django.contrib.auth.models import UserManager
from django.db import models
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

DEFAULT_SLUG = "default"
HEADER = "HTTP_X_WORKSPACE"

# Holds an int (workspace id), a _RequestResolver, or None.
_active = contextvars.ContextVar("conformiti.workspace", default=None)


class NoActiveWorkspace(RuntimeError):
    """Saving a tenant row with nothing to tell which organisation owns it."""


# --------------------------------------------------------------------------- #
# The active workspace
# --------------------------------------------------------------------------- #
def current_id():
    """Id of the active workspace, or None when nothing is active."""
    value = _active.get()
    if value is None or isinstance(value, int):
        return value
    return value.resolve()


def current():
    """The active :class:`Workspace`, or None."""
    wid = current_id()
    if wid is None:
        return None
    from .models import Workspace

    return Workspace.objects.filter(pk=wid).first()


def activate(workspace):
    """Make ``workspace`` (an instance or an id) active until further notice.
    Prefer :func:`scoped` outside the test runner."""
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
    """Run the block with no workspace active: every row of every organisation.
    Only for the platform-level views that need it."""
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
    """The workspace an installation starts with, and the one single-tenant
    deployments never leave. Created by the migration; recreated if lost."""
    from .models import Workspace

    ws, _ = Workspace.objects.get_or_create(slug=DEFAULT_SLUG, defaults={"name": "Default"})
    return ws


def organisation_name():
    """What to call the organisation in outbound mail: the workspace's name
    once there is more than one, else the installation-wide setting."""
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


# --------------------------------------------------------------------------- #
# Resolving the workspace of a request
# --------------------------------------------------------------------------- #
def workspace_id_for(user, wanted=None):
    """Which workspace ``user`` works in. ``wanted`` is the X-Workspace header:
    honoured for a superuser, ignored for everyone else (they are where they
    are). Raises PermissionDenied when the account has nowhere to go."""
    from .models import Workspace

    # Archived workspaces are refused at sign-in and by the authentication
    # class, which loads the workspace in the same query as the user; here
    # only a workspace already on the instance is consulted, so a request
    # costs no extra query.
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
    """Installed by the middleware; resolves and caches the request's
    workspace the first time a tenant query needs it. Re-entrant: resolving
    the user itself runs a User query, which must stay unscoped."""

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
    """Give every request its own resolver and put things back afterwards.
    Must sit inside AuthenticationMiddleware (so the admin's session user is
    visible) and outside AuditLogMiddleware (which writes a tenant row)."""

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


# --------------------------------------------------------------------------- #
# The scoped queryset, manager and model
# --------------------------------------------------------------------------- #
class ActiveWorkspace(models.Expression):
    """A SQL parameter that is the active workspace id at the moment the
    query is compiled. Pinning with this rather than a literal means a
    queryset built under one workspace (or at import time in a test run,
    where one is always active) evaluates in whichever is active when it
    runs, and in none at all when nothing is."""

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
        if self._tenant or self.query.is_sliced or self.query.combinator:
            return self
        if current_id() is None:
            return self  # nothing active: migrations, createsuperuser, jobs that walk every workspace
        self._tenant = True
        self.query.add_q(models.Q(workspace_id=ActiveWorkspace()))
        return self

    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            obj.assign_workspace()
        return super().bulk_create(objs, *args, **kwargs)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    def get_queryset(self):
        return super().get_queryset()._pin()


class TenantUserManager(UserManager.from_queryset(TenantQuerySet)):
    """UserManager (createsuperuser and friends) with the workspace filter."""

    def get_queryset(self):
        return super().get_queryset()._pin()


class TenantModel(models.Model):
    """Inherit to make a model belong to a workspace. Set ``tenant_parent`` to
    the name of the foreign key a new row inherits its workspace from."""

    tenant_parent = None

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="+", editable=False,
    )

    objects = TenantManager()

    class Meta:
        abstract = True

    def assign_workspace(self):
        """Fill ``workspace`` from the parent row, else the active workspace."""
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


# --------------------------------------------------------------------------- #
# DRF helpers
# --------------------------------------------------------------------------- #
class CurrentWorkspaceDefault:
    """``serializers.HiddenField(default=CurrentWorkspaceDefault())``: lets a
    per-workspace unique constraint validate as 400 instead of failing as an
    IntegrityError, and stamps the row on create."""

    requires_context = True

    def __call__(self, serializer_field):
        wid = current_id()
        if wid is None:
            raise PermissionDenied("No workspace is active.")
        return current()

    def __repr__(self):
        return "CurrentWorkspaceDefault()"


def workspace_option(parser):
    """``--workspace SLUG`` for management commands that act on one."""
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
