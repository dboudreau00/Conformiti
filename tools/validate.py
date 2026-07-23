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
              "notifications", "audit", "analytics", "governance", "integrations"]


def apps_with_models():
    out = []
    for app in LOCAL_APPS:
        p = os.path.join(BACKEND, app, "models.py")
        if os.path.exists(p) and re.search(r"class \w+\(.*models\.Model", read(p)):
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

    model_apps = apps_with_models()
    for f in ["backend/entrypoint.sh", "install.sh", "install.ps1", "README.md", "INSTALL.md"]:
        path = os.path.join(ROOT, f)
        if not os.path.exists(path):
            warn("wiring", f"{f} not found")
            continue
        text = read(path)
        m = re.search(r"makemigrations([^\n&|;]*)", text)
        if not m:
            warn("wiring", f"{f}: no makemigrations line found")
            continue
        listed = m.group(1).split()
        missing = [a for a in model_apps if a not in listed]
        if missing:
            err("wiring", f"{f}: makemigrations is missing app(s): {', '.join(missing)}")
    print(f"  2. app wiring: {len(LOCAL_APPS)} apps, migrations lists checked in 5 files")


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
    pages = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(FRONTEND, "pages", "*.jsx"))}
    imported = set(re.findall(r'import (\w+) from "\./pages/(?:\w+)\.jsx"', app))
    routed = set(re.findall(r"element=\{<(\w+)[\s/>]", app))
    for page in pages - {"Login"}:
        if page not in imported:
            err("app", f"pages/{page}.jsx exists but is not imported in App.jsx")
        elif page not in routed:
            err("app", f"{page} is imported but has no <Route> in App.jsx")
    nav_tos = set(re.findall(r'to:\s*"(/[^"]*)"', app))
    route_paths = set(re.findall(r'path="(/[^"]*)"', app))
    titles_block = re.search(r"const TITLES = \{(.*?)\};", app, re.S)
    title_keys = set(re.findall(r'"(/[^"]*)":', titles_block.group(1))) if titles_block else set()
    for to in nav_tos:
        if to not in route_paths:
            err("app", f"nav links to {to} but no Route defines it")
        if to not in title_keys:
            err("app", f"nav links to {to} but TITLES has no entry (topbar would fall back)")
    print(f"  5. App.jsx wiring: {len(pages)} pages, {len(nav_tos)} nav links checked")


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
        for m in re.finditer(r'api\.(?:get|post|patch|put|delete)\(\s*[`"]/([^/`"?]+)', read(f)):
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
    css = read(os.path.join(FRONTEND, "styles", "app.css"))
    defined = set(re.findall(r"\.([a-z][a-z0-9-]*)", css))
    missing = {}
    for f in files:
        for m in re.finditer(r'className=\{?["`]([^"`]+)', read(f)):
            for cls in m.group(1).split():
                if re.fullmatch(r"[a-z][a-z0-9-]+", cls) and cls not in defined:
                    missing.setdefault(cls, os.path.basename(f))
    for cls, where in sorted(missing.items()):
        warn("css", f"class '{cls}' used in {where} but not defined in app.css")
    print(f"  8. css usage: {len(defined)} classes defined, {len(missing)} unknown (warnings)")


# ===========================================================================
# 9. requirements.txt covers third-party imports
# ===========================================================================
PIP_NAME = {
    "django": "django", "rest_framework": "djangorestframework",
    "rest_framework_simplejwt": "djangorestframework-simplejwt",
    "corsheaders": "django-cors-headers", "django_filters": "django-filter",
    "dotenv": "python-dotenv", "celery": "celery", "redis": "redis",
    "boto3": "boto3", "gunicorn": "gunicorn", "psycopg": "psycopg",
    "dateutil": "python-dateutil",
    "psycopg2": "psycopg2-binary",
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
                if m in std or m in LOCAL_APPS or m in ("config",):
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
    used = set(re.findall(r'os\.getenv\(\s*"([A-Z0-9_]+)"', settings))
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

    print()
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"\n{'FAIL' if errors else 'PASS'} — {len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
