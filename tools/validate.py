#!/usr/bin/env python3
"""
Project validation for alpha/beta readiness.

Runs entirely on the stdlib (no Django import, no node) so it works on a bare
checkout before any dependencies are installed. Checks are grouped; the script
prints a section-by-section report and exits non-zero if any ERROR is found
(WARNINGs don't fail the build).

Usage:  python3 tools/validate.py        (from the repo root)
"""
import ast
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend", "src")

errors, warnings = [], []


def err(section, msg):
    errors.append(f"[{section}] {msg}")


def warn(section, msg):
    warnings.append(f"[{section}] {msg}")


def read(path):
    return open(path, encoding="utf-8").read()


# ===========================================================================
# 1. Backend: every .py parses
# ===========================================================================
def check_python_syntax():
    n = 0
    for path in glob.glob(os.path.join(BACKEND, "**", "*.py"), recursive=True):
        n += 1
        try:
            ast.parse(read(path), filename=path)
        except SyntaxError as exc:
            err("py", f"{os.path.relpath(path, ROOT)}: {exc}")
    print(f"  1. python syntax: {n} files parsed")


# ===========================================================================
# 2. Backend wiring: apps, urls, migrations lists
# ===========================================================================
LOCAL_APPS = ["accounts", "compliance", "documents", "calendar_app",
              "notifications", "audit", "analytics", "governance", "integrations",
              "attestations", "vendors"]


def apps_with_models():
    out = []
    for app in LOCAL_APPS:
        p = os.path.join(BACKEND, app, "models.py")
        # Model bases: plain models.Model, the tenant base (0.9.0) and the
        # swapped user model. Matching only "models.Model" silently dropped
        # seven apps out of this check when the tenancy refactor landed.
        if os.path.exists(p) and re.search(
                r"class \w+\(.*(?:models\.Model|TenantModel|AbstractUser)", read(p)):
            out.append(app)
    return out


def check_backend_wiring():
    settings = read(os.path.join(BACKEND, "config", "settings.py"))
    config_urls = read(os.path.join(BACKEND, "config", "urls.py"))
    for app in LOCAL_APPS:
        if f'"{app}"' not in settings and f"'{app}'" not in settings:
            err("wiring", f"app '{app}' missing from INSTALLED_APPS")
        has_urls = os.path.exists(os.path.join(BACKEND, app, "urls.py"))
        if has_urls and f"{app}.urls" not in config_urls:
            err("wiring", f"{app}/urls.py exists but is not included in config/urls.py")

    # Migrations ship with the release: every app that declares models must
    # carry an initial migration, and no install path may run makemigrations
    # (that would generate un-reviewed schema changes on the target machine).
    model_apps = apps_with_models()
    for app in model_apps:
        if not os.path.exists(os.path.join(BACKEND, app, "migrations", "0001_initial.py")):
            err("wiring", f"{app} declares models but ships no migrations/0001_initial.py")
    for f in ["backend/entrypoint.sh", "install.sh", "install.ps1", "docker-compose.yml"]:
        path = os.path.join(ROOT, f)
        if not os.path.exists(path):
            err("wiring", f"{f} not found")
            continue
        if re.search(r"^[^#\n]*\bmakemigrations\b(?!\s+--check)", read(path), re.M):
            err("wiring", f"{f} runs makemigrations at install time — migrations must ship with the release")
    print(f"  2. app wiring: {len(LOCAL_APPS)} apps, {len(model_apps)} migration sets, install paths never makemigrations")


# ===========================================================================
# 3. Every ViewSet is registered in a router
# ===========================================================================
def check_viewset_registration():
    n_sets = 0
    for app in LOCAL_APPS:
        vpath = os.path.join(BACKEND, app, "views.py")
        upath = os.path.join(BACKEND, app, "urls.py")
        if not os.path.exists(vpath):
            continue
        views = read(vpath)
        urls = read(upath) if os.path.exists(upath) else ""
        config_urls = read(os.path.join(BACKEND, "config", "urls.py"))
        for m in re.finditer(r"^class (\w+)\((?:[\w.]+,\s*)*[\w.]*ViewSet\)", views, re.M):
            name = m.group(1)
            n_sets += 1
            if name not in urls and name not in config_urls:
                err("routes", f"{app}.views.{name} is never registered in a urls.py")
    print(f"  3. viewset registration: {n_sets} viewsets verified")


# ===========================================================================
# 4. Frontend: JSX tag-tree validity
# ===========================================================================
def _strip_js(s):
    out, i, n = [], 0, len(s)
    SP = set("([{,:;=?&|!+-*/%<~^\n") | {""}

    def last_sig(j):
        k = j - 1
        while k >= 0 and s[k] in " \t":
            k -= 1
        return s[k] if k >= 0 else ""

    while i < n:
        c = s[i]
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            while i < n and s[i] != "\n":
                out.append(" "); i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            out.append("  "); i += 2
            while i + 1 < n and not (s[i] == "*" and s[i + 1] == "/"):
                out.append("\n" if s[i] == "\n" else " "); i += 1
            out.append("  "); i += 2; continue
        if c == "`":
            out.append(" "); i += 1
            while i < n and s[i] != "`":
                if s[i] == "\\":
                    out.append("  "); i += 2; continue
                out.append("\n" if s[i] == "\n" else " "); i += 1
            out.append(" "); i += 1; continue
        if c in "\"'" and last_sig(i) in SP:
            q = c; out.append(" "); i += 1
            while i < n and s[i] != q:
                if s[i] == "\\":
                    out.append("  "); i += 2; continue
                out.append("\n" if s[i] == "\n" else " "); i += 1
            out.append(" "); i += 1; continue
        out.append(c); i += 1
    return "".join(out)


def _check_jsx(path):
    t = _strip_js(read(path))
    n, i, stack, line = len(t), 0, [], 1
    while i < n:
        c = t[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c == "<" and i + 1 < n and (t[i + 1].isalpha() or t[i + 1] in "/>"):
            j, closing = i + 1, False
            if t[j] == "/":
                closing = True; j += 1
            name = ""
            while j < n and (t[j].isalnum() or t[j] in "._"):
                name += t[j]; j += 1
            depth, selfclose = 0, False
            while j < n:
                cj = t[j]
                if cj == "{":
                    depth += 1
                elif cj == "}":
                    depth -= 1
                elif cj == ">" and depth == 0:
                    if j > 0 and t[j - 1] == "/":
                        selfclose = True
                    break
                elif cj == "\n":
                    line += 1
                j += 1
            if not name:  # fragment
                if closing:
                    if not stack:
                        return f"{path}:{line} stray fragment close"
                    stack.pop()
                else:
                    stack.append((name, line))
            elif selfclose:
                pass
            elif closing:
                if not stack:
                    return f"{path}:{line} </{name}> without open"
                top, tl = stack.pop()
                if top != name:
                    return f"{path}:{line} expected </{top}> (opened L{tl}) got </{name}>"
            else:
                stack.append((name, line))
            i = j + 1; continue
        i += 1
    if stack:
        return f"{path} unclosed <{stack[-1][0]}> from L{stack[-1][1]}"
    return None


def check_frontend_syntax():
    files = sorted(glob.glob(os.path.join(FRONTEND, "**", "*.jsx"), recursive=True)) + \
            sorted(glob.glob(os.path.join(FRONTEND, "**", "*.js"), recursive=True))
    for f in files:
        r = _check_jsx(f)
        if r:
            err("jsx", r)
    print(f"  4. jsx/js structure: {len(files)} files validated")
    return files


# ===========================================================================
# 5. App.jsx consistency: pages imported+routed, nav <-> routes <-> titles
# ===========================================================================
def check_app_wiring():
    app = read(os.path.join(FRONTEND, "App.jsx"))
    nav = read(os.path.join(FRONTEND, "nav.js"))
    pages = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(FRONTEND, "pages", "*.jsx"))}
    imported = set(re.findall(r'import (\w+) from "\./pages/(?:\w+)\.jsx"', app))
    routed = set(re.findall(r"element=\{<(\w+)[\s/>]", app))
    for page in pages - {"Login"}:
        if page not in imported:
            err("app", f"pages/{page}.jsx exists but is not imported in App.jsx")
        elif page not in routed:
            err("app", f"{page} is imported but has no <Route> in App.jsx")
    nav_paths = set(re.findall(r'path:\s*"(/[^"]*)"', nav))
    route_paths = set(re.findall(r'path="(/[^"]*)"', app))
    lookup_block = re.search(r"const NAV_LOOKUP = \{(.*?)\};", nav, re.S)
    lookup_keys = set(re.findall(r'"(/[^"]*)":', lookup_block.group(1))) if lookup_block else set()
    for to in nav_paths:
        if to not in route_paths:
            err("app", f"nav.js links to {to} but App.jsx defines no Route for it")
        if to not in lookup_keys:
            err("app", f"nav.js links to {to} but NAV_LOOKUP has no title/caption for it")
    # every routed page is a PanelTransition page (shell animation contract)
    for page in pages - {"Login"}:
        src = read(os.path.join(FRONTEND, "pages", f"{page}.jsx"))
        if "PanelTransition" not in src:
            err("app", f"pages/{page}.jsx does not use <PanelTransition> as its root")
    print(f"  5. App.jsx wiring: {len(pages)} pages, {len(nav_paths)} nav links checked")


# ===========================================================================
# 6. Frontend API calls resolve to backend routes
# ===========================================================================
def backend_prefixes():
    prefixes = set()
    for app in LOCAL_APPS:
        upath = os.path.join(BACKEND, app, "urls.py")
        if not os.path.exists(upath):
            continue
        u = read(upath)
        prefixes |= set(re.findall(r'router\.register\(\s*"([^"]+)"', u))
        prefixes |= {p.split("/")[0] for p in re.findall(r'path\(\s*"([^"]+)"', u) if p}
    cfg = read(os.path.join(BACKEND, "config", "urls.py"))
    prefixes |= {m.split("/")[1] for m in re.findall(r'path\(\s*"(api/[^"]+)"', cfg)}
    return prefixes


def check_api_calls(files):
    prefixes = backend_prefixes()
    n = 0
    for f in files:
        for m in re.finditer(r'(?:api\.(?:get|post|patch|put|delete)|fetchAll|downloadFile)\(\s*[`"]/([^/`"?]+)', read(f)):
            n += 1
            seg = m.group(1)
            if seg not in prefixes:
                err("api", f"{os.path.relpath(f, ROOT)} calls /{seg}/… but no backend route starts with that")
    print(f"  6. api surface: {n} frontend calls resolved against {len(prefixes)} backend prefixes")


# ===========================================================================
# 7. Frontend relative imports resolve
# ===========================================================================
def check_frontend_imports(files):
    n = 0
    for f in files:
        for m in re.finditer(r'from "(\.\.?/[^"]+)"', read(f)):
            n += 1
            target = os.path.normpath(os.path.join(os.path.dirname(f), m.group(1)))
            if not (os.path.exists(target) or os.path.exists(target + ".js") or os.path.exists(target + ".jsx")):
                err("imports", f"{os.path.relpath(f, ROOT)}: unresolved import {m.group(1)}")
    print(f"  7. frontend imports: {n} relative imports resolved")


# ===========================================================================
# 8. CSS classes used in JSX exist in app.css
# ===========================================================================
def check_css(files):
    """The design system is token-driven (styles/index.css + Tailwind). Every
    theme pack and accent pack must be defined, nothing may import the
    retired app.css, and pages must not hard-code colours that would break
    the light/dark packs."""
    css_path = os.path.join(FRONTEND, "styles", "index.css")
    if not os.path.exists(css_path):
        err("css", "frontend/src/styles/index.css missing")
        return
    css = read(css_path)
    for pack in ("ledger", "nimbus", "ledger-dark", "obsidian"):
        if f'[data-theme="{pack}"]' not in css:
            err("css", f"theme pack '{pack}' is not defined in styles/index.css")
    for accent in ("pine", "azure", "violet", "ember"):
        if f'[data-accent="{accent}"]' not in css:
            err("css", f"accent pack '{accent}' is not defined in styles/index.css")
    for token in ("--bg", "--surface", "--surface-2", "--line", "--ink", "--muted", "--faint", "--accent", "--accent-ink", "--success", "--warning", "--danger", "--info", "--grid"):
        if f"{token}:" not in css:
            err("css", f"token {token} is not defined in styles/index.css")
    if os.path.exists(os.path.join(FRONTEND, "styles", "app.css")):
        err("css", "retired styles/app.css is still present")
    hard = {}
    for f in files:
        src = read(f)
        if "app.css" in src:
            err("css", f"{os.path.relpath(f, ROOT)} still imports app.css")
        if os.path.basename(f) in ("theme.js", "brand.js") or os.sep + "brand" + os.sep in f:
            continue  # swatch data and the identity's fixed colourways, not styling
        for m in re.finditer(r"#[0-9a-fA-F]{6}\b", src):
            hard.setdefault(os.path.relpath(f, ROOT), 0)
            hard[os.path.relpath(f, ROOT)] += 1
    for where, n in sorted(hard.items()):
        warn("css", f"{where} hard-codes {n} hex colour(s) — use theme tokens")
    print(f"  8. theme system: 4 theme packs + 4 accent packs defined, {len(hard)} file(s) with hard-coded colours (warnings)")


# ===========================================================================
# 9. requirements.txt covers third-party imports
# ===========================================================================
PIP_NAME = {
    "jwt": "PyJWT",
    "signxml": "signxml",
    "lxml": "lxml",
    "django": "django", "rest_framework": "djangorestframework",
    "rest_framework_simplejwt": "djangorestframework-simplejwt",
    "corsheaders": "django-cors-headers", "django_filters": "django-filter",
    "dotenv": "python-dotenv", "celery": "celery", "redis": "redis",
    "boto3": "boto3", "gunicorn": "gunicorn", "psycopg": "psycopg",
    "dateutil": "python-dateutil",
    "psycopg2": "psycopg2-binary",
    "cryptography": "cryptography",
    "storages": "django-storages",
}


def check_requirements():
    req_path = os.path.join(BACKEND, "requirements.txt")
    req = read(req_path).lower()
    std = set(sys.stdlib_module_names)
    seen = set()
    for path in glob.glob(os.path.join(BACKEND, "**", "*.py"), recursive=True):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in std or m in LOCAL_APPS or m in ("config", "testutils"):
                    continue
                seen.add(m)
    for mod in sorted(seen):
        pip = PIP_NAME.get(mod)
        if pip is None:
            warn("deps", f"unmapped third-party import '{mod}' — verify it's in requirements.txt")
        elif pip.lower() not in req:
            err("deps", f"'{mod}' is imported but '{pip}' is not in requirements.txt")
    print(f"  9. dependencies: {len(seen)} third-party modules checked against requirements.txt")


# ===========================================================================
# 10. Deploy artifacts: docker-compose, dockerfiles, env example
# ===========================================================================
def check_deploy():
    dc_path = os.path.join(ROOT, "docker-compose.yml")
    if os.path.exists(dc_path):
        dc = read(dc_path)
        for m in re.finditer(r"dockerfile:\s*(\S+)|context:\s*(\S+)", dc):
            pass  # contexts checked below
        for rel in re.findall(r"context:\s*\./(\S+)", dc):
            if not os.path.isdir(os.path.join(ROOT, rel)):
                err("deploy", f"docker-compose context ./{rel} does not exist")
    else:
        warn("deploy", "docker-compose.yml missing")
    if not os.path.exists(os.path.join(BACKEND, "entrypoint.sh")):
        err("deploy", "backend/entrypoint.sh missing")
    settings = read(os.path.join(BACKEND, "config", "settings.py"))
    envex = read(os.path.join(ROOT, ".env.example"))
    used = set(re.findall(r'(?:os\.getenv|env_bool|env_int)\(\s*"([A-Z0-9_]+)"', settings))
    documented = set(re.findall(r"^#?\s*([A-Z0-9_]+)=", envex, re.M))
    for key in sorted(used - documented):
        warn("deploy", f"settings reads env '{key}' but .env.example doesn't mention it")
    print(f" 10. deploy artifacts: compose/entrypoint present, {len(used)} env keys cross-checked")


# ===========================================================================
# 11. Demo-data integrity: seeded control ids exist in the framework JSON
# ===========================================================================
def check_demo_data():
    ids = {}
    for key in ["soc2", "iso27001", "pci_dss_v4"]:
        data = json.load(open(os.path.join(BACKEND, "compliance", "data", f"{key}.json")))
        ids[key] = {c["control_id"] for cat in data["categories"] for c in cat["controls"]}
    boot = read(os.path.join(BACKEND, "accounts", "management", "commands", "bootstrap_demo.py"))
    refs = re.findall(r'\(\s*"(soc2|iso27001|pci_dss_v4)"\s*,\s*"([^"]+)"\s*\)', boot)
    for fw, cid in refs:
        if cid not in ids[fw]:
            err("demo", f"bootstrap references {fw}:{cid} which is not in the seed data")
    print(f" 11. demo data: {len(refs)} seeded control references verified against framework JSON")


# ===========================================================================
# 12. Risk importer regression (pure-stdlib module, runs standalone)
# ===========================================================================
def check_importer():
    sys.path.insert(0, BACKEND)
    from governance.risk_import import parse_upload, normalize
    recs, issues, fatal = normalize(parse_upload(
        "t.csv", b"Title,Probability,Severity,Due date\nX,High,4,2026-09-01\n"))
    assert fatal is None and recs[0]["likelihood"] == 4 and recs[0]["impact"] == 4, "csv path"
    sample = os.path.join(ROOT, "docs", "sample-risk-import.csv")
    recs, issues, fatal = normalize(parse_upload("s.csv", open(sample, "rb").read()))
    if fatal or len(recs) != 4 or issues:
        err("importer", f"sample-risk-import.csv: {fatal or f'{len(recs)} recs, {len(issues)} warnings'}")
    print(" 12. risk importer: fixture + sample file regression passed")


def check_mfa():
    sys.path.insert(0, BACKEND)
    import base64
    from accounts import mfa
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    hotp_expected = ["755224", "287082", "359152", "969429", "338314",
                     "254676", "287922", "162583", "399871", "520489"]
    for counter, exp in enumerate(hotp_expected):
        if mfa.hotp(secret, counter) != exp:
            err("mfa", f"HOTP vector {counter} mismatch (RFC 4226)")
    for t, exp in [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924")]:
        if mfa.totp(secret, at=t, digits=8) != exp:
            err("mfa", f"TOTP vector t={t} mismatch (RFC 6238)")
    # generated secret round-trips through verify()
    gen = mfa.generate_secret()
    if not mfa.verify(gen, mfa.totp(gen, at=1720000000), at=1720000000):
        err("mfa", "generated-secret TOTP round trip failed")
    print(" 13. mfa engine: RFC 4226/6238 vectors + round trip passed")


def check_notifications_wiring():
    """The review-reminder email chain has async/scheduled parts the other
    checks don't reach: prove every link is connected end to end."""
    settings = read(os.path.join(BACKEND, "config", "settings.py"))
    tasks = read(os.path.join(BACKEND, "notifications", "tasks.py"))
    svc = read(os.path.join(BACKEND, "notifications", "email_service.py"))
    initpy = read(os.path.join(BACKEND, "config", "__init__.py"))
    docs_models = read(os.path.join(BACKEND, "documents", "models.py"))

    # 1. beat schedule task name resolves to a registered @shared_task
    m = re.search(r'"task":\s*"([\w.]+)"', settings)
    if not m:
        err("notify", "no task wired into CELERY_BEAT_SCHEDULE")
    elif f'name="{m.group(1)}"' not in tasks and f"name='{m.group(1)}'" not in tasks:
        err("notify", f"beat task {m.group(1)} has no matching @shared_task(name=...)")

    # 2. celery app is imported at startup
    if "celery_app" not in initpy:
        err("notify", "config/__init__.py does not import the Celery app")

    # 3. cron-mode management command exists and calls the scan
    cmd = os.path.join(BACKEND, "notifications", "management", "commands", "send_review_reminders.py")
    if not os.path.exists(cmd):
        err("notify", "send_review_reminders management command missing")
    elif "run_review_scan" not in read(cmd):
        err("notify", "send_review_reminders does not call run_review_scan")

    # 4. both email templates exist
    for ext in ("html", "txt"):
        t = os.path.join(BACKEND, "notifications", "templates", "emails", f"review_reminder.{ext}")
        if not os.path.exists(t):
            err("notify", f"email template review_reminder.{ext} missing")

    # 5. provider dispatch covers every documented EMAIL_PROVIDER
    for provider in ("ses", "mailbox"):
        if f'"{provider}"' not in svc:
            err("notify", f"email_service has no branch for EMAIL_PROVIDER={provider}")

    # 6. model fields the scan depends on
    if "reminders_sent" not in docs_models:
        err("notify", "Document.reminders_sent field missing (dedupe state)")
    if "EXPIRED" not in docs_models:
        err("notify", "Document.Status.EXPIRED missing (overdue marking)")

    # 7. lead-day windows configured
    if "REVIEW_ALERT_LEAD_DAYS" not in settings:
        err("notify", "REVIEW_ALERT_LEAD_DAYS not configured")

    print(" 14. review-reminder wiring: beat/task/command/templates/model all connected")




def check_compose_debug_isolation():
    """Compose reads ./.env both for ${...} substitution and into the
    containers, and ./.env is what the *local* installer writes (DEBUG on, dev
    signing key). The Docker stack must therefore never interpolate
    DJANGO_DEBUG / DJANGO_SECRET_KEY, or a developer who ran ./install.sh and
    then `docker compose up` gets a DEBUG container signing real tokens."""
    path = os.path.join(ROOT, "docker-compose.yml")
    if not os.path.exists(path):
        err("compose", "docker-compose.yml missing")
        return
    dc = read(path)
    # Every secret the stack accepts must go through a CONFORMITI_* name that a
    # development .env never contains. Adding a secret here without adding it to
    # this list is how the class of bug comes back.
    for leaky in ("${DJANGO_DEBUG", "${DJANGO_SECRET_KEY:", "${DJANGO_FIELD_ENCRYPTION_KEY:"):
        if leaky in dc:
            err("compose", f"docker-compose.yml interpolates {leaky}...}} from .env — "
                           "use the matching CONFORMITI_* variable instead")
    if "DJANGO_DEBUG: ${CONFORMITI_DEBUG:-false}" not in dc:
        err("compose", "docker-compose.yml must set DJANGO_DEBUG from ${CONFORMITI_DEBUG:-false}")
    for required in ("DJANGO_SECRET_KEY_FILE:", "DJANGO_FIELD_ENCRYPTION_KEY_FILE:"):
        if required not in dc:
            err("compose", f"docker-compose.yml must set {required} so a key is generated on first boot")
    envex = read(os.path.join(ROOT, ".env.example"))
    for key in ("CONFORMITI_DEBUG", "CONFORMITI_SECRET_KEY", "CONFORMITI_FIELD_ENCRYPTION_KEY"):
        if key not in envex:
            err("compose", f"{key} is not documented in .env.example")
    print(" 16. compose isolation: no secret can leak from a local .env into a container")


def check_malware_scanning():
    """The scanning path, checked without a socket or a ClamAV install.

    Three things can silently make "evidence is scanned" untrue: a clamd that
    skips oversized content and answers OK, a compose file that reads the
    enable flag from a shared .env, and a stream limit smaller than what nginx
    will accept.
    """
    # documents.clamav ONLY: this script runs on a bare checkout before
    # anything is pip-installed, and documents.scanning imports Django.
    sys.path.insert(0, BACKEND)
    try:
        from documents.clamav import (  # noqa: E402
            InfectedError, LimitsExceededError, ScanError, eicar_bytes, parse_response,
        )
    except Exception as exc:  # pragma: no cover - import failure is the finding
        err("scanning", f"documents.clamav did not import on a bare checkout: {exc}. "
                        "Check 17 must depend on nothing but the standard library.")
        print(" 17. malware scanning: FAILED to import")
        return

    # The four replies clamd can give.
    cases = 0
    if parse_response("stream: OK") is not None:
        err("scanning", "a clean reply must map to None")
    cases += 1
    for reply, expected in [
        ("stream: Win.Test.EICAR_HDB-1 FOUND", InfectedError),
        ("stream: Heuristics.Limits.Exceeded.MaxFileSize FOUND", LimitsExceededError),
        ("stream: something ERROR", ScanError),
        ("", ScanError),
    ]:
        try:
            parse_response(reply)
            err("scanning", f"{reply!r} should have raised {expected.__name__}")
        except expected:
            pass
        except Exception as exc:
            err("scanning", f"{reply!r} raised {type(exc).__name__}, expected {expected.__name__}")
        cases += 1

    eicar = eicar_bytes()
    if len(eicar) != 68 or not eicar.startswith(b"X5O!"):
        err("scanning", "the EICAR test string is not the standard 68-byte file")

    # The three numbers that have to agree with each other.
    conf_path = os.path.join(ROOT, "docker", "clamd.conf")
    if not os.path.exists(conf_path):
        err("scanning", "docker/clamd.conf is missing; the scanning profile cannot start")
    else:
        conf = read(conf_path)
        if "AlertExceedsMax yes" not in conf:
            err("scanning", "docker/clamd.conf must set 'AlertExceedsMax yes', or content that "
                            "trips a Max* limit is skipped and answered OK")
        if "StreamMaxLength 40M" not in conf:
            err("scanning", "docker/clamd.conf must set StreamMaxLength 40M to match CLAMAV_MAX_MB")

    nginx = os.path.join(ROOT, "frontend", "nginx.conf")
    if os.path.exists(nginx) and "client_max_body_size 32m" not in read(nginx):
        err("scanning", "frontend/nginx.conf must cap bodies at 32m to match MAX_UPLOAD_MB")

    print(f" 17. malware scanning: {cases} protocol cases, EICAR fixture and the "
          "clamd/nginx limits agree")


def check_tests_and_ci():
    """A shippable project carries its own proof: a test module per app and
    a CI workflow that runs them."""
    missing = [app for app in LOCAL_APPS
               if not (os.path.exists(os.path.join(BACKEND, app, "tests.py"))
                       or os.path.isdir(os.path.join(BACKEND, app, "tests")))]
    for app in missing:
        err("tests", f"{app} has no tests.py / tests/ package")
    n_tests = 0
    for path in glob.glob(os.path.join(BACKEND, "**", "tests.py"), recursive=True):
        n_tests += len(re.findall(r"^\s+def test_", read(path), re.M))
    if not os.path.exists(os.path.join(ROOT, ".github", "workflows", "ci.yml")):
        err("tests", ".github/workflows/ci.yml missing")
    if not os.path.exists(os.path.join(ROOT, "LICENSE")):
        err("tests", "LICENSE file missing")
    print(f" 15. tests + ci: {n_tests} test functions across {len(LOCAL_APPS) - len(missing)}/{len(LOCAL_APPS)} apps, workflow + LICENSE present")


# ===========================================================================
def main():
    print(f"Validating {ROOT}\n")
    check_python_syntax()
    check_backend_wiring()
    check_viewset_registration()
    files = check_frontend_syntax()
    check_app_wiring()
    check_api_calls(files)
    check_frontend_imports(files)
    check_css(files)
    check_requirements()
    check_deploy()
    check_demo_data()
    check_importer()
    check_mfa()
    check_notifications_wiring()
    check_tests_and_ci()
    check_compose_debug_isolation()
    check_malware_scanning()

    print()
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"\n{'FAIL' if errors else 'PASS'} — {len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
