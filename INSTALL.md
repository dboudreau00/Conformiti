# Install

Three ways to run Conformiti, from "just show me" to production.

| Path | Best for | Needs | Command |
|---|---|---|---|
| **Docker** | evaluating, LAN pilots, production | Docker Engine 24+ / Docker Desktop with Compose 2.24 or newer | `docker compose up -d --build` |
| **Local dev** | hacking on the code | Python 3.11+, Node 20.19+ or 22.12+ | `./install.sh` / `.\install.ps1` |
| **Manual** | custom hosting, bare metal (Linux) | as above + PostgreSQL, Redis, nginx | see §3 |

**On Windows**, run the local development path (§2), or the Docker stack
under Docker Desktop or WSL 2, for development and evaluation. Run production
on a Linux host, with Docker (§1) or on bare metal (§3). The bare-metal recipe
in §3 is Linux-only (gunicorn does not run on Windows), and this repository
ships no Windows service setup.

---

## 1. Docker (recommended)

```bash
git clone https://github.com/dboudreau00/Conformiti.git
cd Conformiti
docker compose up -d --build
```

Then open **http://localhost:8080**. Create the first account with
`docker compose exec backend python manage.py createsuperuser`. Its password
must pass the same policy as every other account's: at least
`PASSWORD_MIN_LENGTH` characters (12 by default), not a common password, not
all digits, and not too close to the username or email. A password that fails
is refused, with no bypass, and no account is created.

To look around a worked example instead, put `SEED_DEMO_DATA=true` in `.env`
(create the file if there is none) before you run `docker compose up`, or use
`--demo` with the scripted variant below. That seeds five accounts sharing one
password, generated on first boot and printed once
(`docker compose logs backend | grep "Sign in as"`, or set `DEMO_PASSWORD` in
`.env` beforehand). It is off by default: an installation carrying those
accounts says so on its own sign-in page, which is not a thing a real
deployment should publish.

Keep settings like these in `.env`. Compose reads that file on every start
and hands it to the application containers; a variable exported in your
shell is seen only by commands run from that shell, and only for the keys
`docker-compose.yml` passes through.

What happens on first boot:

1. PostgreSQL 16 and Redis 7 start with healthchecks.
2. The API container waits for the database, applies the shipped migrations,
   seeds the three control libraries (217 controls, 1,117 folders) and the
   built-in roles, seeds the demo dataset only if you asked for it
   (`SEED_DEMO_DATA=true`), collects static files and starts gunicorn as an
   unprivileged user.
3. A strong `DJANGO_SECRET_KEY` is generated and persisted in the `secrets`
   volume, so no placeholder ever signs a token.
4. The Celery `worker` and `beat` services start once the API is *healthy*.
   `beat` schedules the daily review scan (06:00 by default), the readiness
   snapshot, the digests, the hourly malware-scanner check and the weekly
   blacklist pruning; the worker runs them.
5. nginx serves the built SPA, proxies `/api/` and `/admin/`, and serves
   uploads and static files from shared volumes.

The API is also published on the host's loopback, `127.0.0.1:8000`, for
debugging (`CONFORMITI_API_PORT` to move it); the LAN only sees nginx on port
8080 (`CONFORMITI_PORT` to change it). Both host ports must be free.

### The scripted variant

```bash
./install.sh --docker            # macOS / Linux / WSL
.\install.ps1 -Docker            # Windows PowerShell
```

The script checks Docker is running, writes a production-style `.env` if you
don't have one (DEBUG off, a unique key, your hostname in `ALLOWED_HOSTS`),
builds and starts the stack, **waits until `/api/health/` reports `ok`**, and
prints the URLs. Flags: `--demo` / `-Demo` (load the sample organisation),
`--open` / `-Open`, `--port N` / `-Port N`.

With a `.env` already in place, the script leaves it alone unless a flag
disagrees with it: `--demo` / `--no-demo` (`-Demo` / `-NoDemo`) rewrite
`SEED_DEMO_DATA`, and `--port N` (`-Port N`) rewrites `CONFORMITI_PORT` and
moves the `http://localhost` and `http://127.0.0.1` entries of
`CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` from the old port to the new
one. Each change is printed. `--no-demo` stops the seeding; accounts already
created stay until `remove_demo_data`.

When the running stack reports demo accounts, the closing banner shows their
password, which it reads from `docker compose logs backend`. The password is
logged once, by the container that created the accounts; once that log is
gone, the banner says so and gives the command that sets a new one:
`docker compose exec backend python manage.py changepassword admin`.

**Windows PowerShell and the execution policy.** On a default Windows 10 or 11
client, Windows PowerShell 5.1 refuses every script with *running scripts is
disabled on this system*. Run the installer with a bypass that lasts only for
that one process and changes no setting:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Docker
```

or run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once in
the window, then `.\install.ps1` as usual. PowerShell 7 (`pwsh`) runs local
scripts by default but not downloaded ones: if you took the ZIP rather than
cloning, run `Unblock-File .\install.ps1` first, or use the same bypass.

### Without a build: the published images

Every release is published as two images on this repository's registry, built
for `linux/amd64` and `linux/arm64`:

```bash
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

`docker-compose.ghcr.yml` swaps the four services that would be built
(`backend`, `worker`, `beat`, `frontend`) for `ghcr.io/dboudreau00/conformiti-backend`
and `ghcr.io/dboudreau00/conformiti-frontend`, and changes nothing else: the
environment, the volumes, the healthchecks and the published ports are
still the ones in `docker-compose.yml`, and first boot runs exactly as above.
Like the base file, it needs Compose 2.24 or newer.

`latest` follows the newest release. Pin the version in production, and pin it
in both commands, because `pull` and `up` each read it:

```bash
export CONFORMITI_VERSION=0.9.5k
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

Keep both files for as long as the installation runs from them. The commands
in the rest of this document are written in the short form,
`docker compose up -d`, which reads `docker-compose.yml` alone: on an
installation started from the published images it builds the four services
from whatever source is checked out and replaces the running release with
that build. Either repeat `-f docker-compose.yml -f docker-compose.ghcr.yml`
on every `up` and `pull`, or name both files once in `.env`, which Compose
reads for every command run in this directory, so the short forms (and
`scripts/restore.sh`, which uses them) stay on the images:

```ini
COMPOSE_FILE=docker-compose.yml:docker-compose.ghcr.yml
CONFORMITI_VERSION=0.9.5k
```

Separate the two files with `;` instead of `:` when you run Docker Desktop's
Windows `docker.exe` rather than Docker inside WSL 2.

A container will tell you what it is: `curl -s localhost:8080/api/health/`
reports the version compiled into the image, and
`docker inspect ghcr.io/dboudreau00/conformiti-backend:0.9.5k` carries the
commit it was built from in `org.opencontainers.image.revision`.

Building from source remains the default, and stays supported: the images are
built from the same two Dockerfiles in this repository, by a workflow that
pulls what it pushed and boots it before the run is allowed to pass.

### Going to production

1. Set the real hostname in `.env`:
   ```ini
   DJANGO_ALLOWED_HOSTS=grc.example.com
   CSRF_TRUSTED_ORIGINS=https://grc.example.com
   CORS_ALLOWED_ORIGINS=https://grc.example.com
   BEHIND_TLS=true            # once TLS is terminated in front of nginx
   NUM_PROXIES=2              # the terminator AND the shipped nginx
   SECURE_HSTS_SECONDS=31536000
   EMAIL_PROVIDER=smtp        # + EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD
   POSTGRES_PASSWORD=<something long>
   REDIS_PASSWORD=<letters and digits>
   ```
   `NUM_PROXIES` is how many hops back along `X-Forwarded-For` the client's
   address is. The default of 1 is the shipped nginx on its own. Put a TLS
   terminator in front of it, which is the next step, and there are two:
   leaving it at 1 makes the terminator's address every visitor's address, so
   they share one rate-limit bucket and a single unauthenticated caller can
   spend the installation's login budget for everybody. The stack warns at
   boot if `BEHIND_TLS` is on and this is still 1. Set it to 1 if your
   terminator replaces the header rather than appending to it, and 0 if the
   API is exposed with nothing in front at all.

   `POSTGRES_PASSWORD` takes effect only when the database volume is first
   created. If the stack has already booted, the database keeps the password
   it was created with (the default is `compliance`), and changing `.env`
   alone leaves the API unable to sign in to its own database. Change the
   password inside the database first, then put the same value in `.env` and
   recreate (use your `POSTGRES_USER` if you changed it):
   ```bash
   docker compose exec db psql -U compliance -c "ALTER USER compliance PASSWORD 'something-long'"
   docker compose up -d
   ```
   Started from the published images? Give that `up` the same two `-f` files
   (or set `COMPOSE_FILE`, as *Without a build* shows), or it rebuilds the
   stack from source.
2. Terminate TLS (Caddy, Traefik, a load balancer) in front of port 8080.
   Your terminator must **set** `X-Forwarded-Proto: https`, not forward
   whatever the client sent; all of them do by default. Conformiti only
   believes that header once `BEHIND_TLS=true` says a terminator exists, so
   one that forwards the client's value instead will redirect in a loop.
3. Create your own administrator, and retire the demo data if you loaded it:
   ```bash
   docker compose exec backend python manage.py createsuperuser
   docker compose exec backend python manage.py remove_demo_data
   ```
   The retirement is recorded, so it holds across restarts even while
   `SEED_DEMO_DATA=true` stays in `.env`: each boot logs
   `Demo data not seeded: ...` instead of seeding the demo back. Set the line
   to `false` anyway, so `.env` says what the installation does, and run
   `manage.py bootstrap_demo --force` if you ever want the demo back (it
   reactivates the demo accounts, and from then on a boot with
   `SEED_DEMO_DATA=true` refreshes the demo until `remove_demo_data`
   retires it once more; the audit log keeps both the retirement and the
   revival). The dataset is off by default.

   To have an account to sign in with from the first boot instead, put
   `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` and
   `DJANGO_SUPERUSER_EMAIL` in `.env`, or export them in the shell you start
   the stack from, before the first boot. The password must pass the policy
   in §1: if it does not, no account is created, the backend log says why,
   and the stack boots without one. Give `DJANGO_SUPERUSER_EMAIL` a real
   address: left unset it is `admin@localhost`. Earlier releases used
   `admin@example.com`, the demo administrator's address, and an account
   named `admin` with that address is counted as a demo account until its
   email changes.
4. Confirm: `curl -s https://grc.example.com/api/health/` returns
   `{"status":"ok","version":"<your version>","database":"ok","demo_accounts":false,…}`.
5. Put `scripts/backup.sh` on cron and copy its output off the machine. It
   takes the database dump and the evidence, secrets and tree volumes in one
   go; `scripts/restore.sh <directory>` brings an installation back, here or
   on another machine. CI runs both on every push. On the published images,
   the restore stays on them only with `COMPOSE_FILE` and
   `CONFORMITI_VERSION` (the backup's release) in `.env`, as *Without a
   build* shows: the script takes no `-f` files, without `COMPOSE_FILE` it
   builds the stack from source, and without `CONFORMITI_VERSION` it runs
   `latest`, which migrates the restored database forward for good. `.env` is
   not in the backup, so on a new machine write both into it before
   restoring.

### Single sign-on (OpenID Connect)

Optional. Nothing changes until all three of the first keys are set.

1. Register Conformiti at your identity provider as a **confidential web
   application** using the authorization-code flow, with the redirect URI
   `https://grc.example.com/api/auth/oidc/callback/` and the scopes
   `openid email profile`. Okta, Entra ID, Google Workspace, Keycloak and
   Authentik all work; anything that publishes
   `/.well-known/openid-configuration` should.
2. Add to `.env` and restart:
   ```ini
   OIDC_ISSUER=https://login.example.com      # exactly the issuer the provider publishes
   OIDC_CLIENT_ID=...
   OIDC_CLIENT_SECRET=...
   OIDC_LABEL=Sign in with Okta               # the button text
   OIDC_ALLOWED_DOMAINS=example.com           # who may sign in through it
   ```
3. On a person's first SSO sign-in, a verified email that matches exactly one
   local account links it. Administrator accounts (superuser, staff, or any
   role that can manage users) are never linked this way, and a linked user
   who is later promoted loses SSO until an operator re-affirms it. Link
   them deliberately:
   ```bash
   docker compose exec backend python manage.py link_oidc_identity admin <subject> --allow-privileged
   ```
   Pre-link anyone else the same way (without the flag) to skip the email match.
4. To create accounts for people the provider vouches for but who have no
   local account yet, set `OIDC_AUTO_PROVISION=true` and `OIDC_DEFAULT_ROLE`
   (default `Viewer`; a role that can manage users is refused).

Entra ID often omits `email_verified`; set `OIDC_REQUIRE_VERIFIED_EMAIL=false`
only when the tenant is your own.

### Single sign-on (SAML 2.0)

For providers that insist on SAML. Same rules as OIDC, same account linking.

1. In the provider, create a SAML application for Conformiti. Give it the SP
   metadata from `https://grc.example.com/api/auth/saml/metadata/` (available
   once step 2 is done), or enter by hand: entity ID
   `https://grc.example.com/api/auth/saml/metadata/`, ACS URL
   `https://grc.example.com/api/auth/saml/acs/`, HTTP-POST binding, NameID
   format email address, and have it send an `email` attribute (plus
   `givenName`/`sn` if you want names filled in).
2. Add to `.env` and restart:
   ```ini
   SAML_IDP_ENTITY_ID=https://idp.example.com/metadata     # exactly as the provider publishes it
   SAML_IDP_SSO_URL=https://idp.example.com/sso/saml       # its HTTP-Redirect sign-on URL
   SAML_IDP_CERT_FILE=/app/secrets/idp.pem                 # its signing certificate (PEM)
   SAML_LABEL=Sign in with SAML
   ```
   Paste the certificate into `SAML_IDP_CERT` instead if you prefer; either
   way it is the only thing the app trusts: responses signed by anything
   else are refused. When the provider rotates its certificate, replace it
   here.
3. Linking, provisioning and the domain allow-list follow the `OIDC_*`
   settings unless a `SAML_*` twin overrides them (`SAML_ALLOWED_DOMAINS`,
   `SAML_AUTO_PROVISION`, `SAML_DEFAULT_ROLE`, `SAML_LINK_BY_EMAIL`).
   `manage.py link_oidc_identity --issuer <entity id>` pre-links an account
   to its SAML NameID.

SAML needs TLS: the provider posts back cross-site, and the cookie that
carries the sign-in state is `SameSite=None; Secure`. Over plain http on a
developer's box the flow may not complete in every browser.

### Second factor on single sign-on

`SSO_STEP_UP` decides what happens when the provider signed someone in but did
not say a second factor was used (OIDC `amr`, SAML `AuthnContextClassRef`):

| Value | Effect |
|---|---|
| `if_enrolled` (default) | a person with a local authenticator is asked for its code before the tokens are issued; one without is let in |
| `required` | the provider must assert a second factor, or the person must have a local authenticator; otherwise the sign-in is refused with a message telling them to enrol one by signing in with their password first |
| `off` | trust the provider |

`SSO_MFA_ASSERTIONS` is the list of values that count as an asserted second
factor; the default covers the usual OIDC `amr` values and SAML context
classes, including Entra ID's `multipleauthn`.

### Passkeys and security keys

On with no configuration: people enrol from *Settings › Security › Passkeys*
and are then asked for the key after their password (or at the SSO step-up).
Two things to know:

- Browsers only offer passkeys on **https** (or `localhost`). A LAN
  deployment on plain http will show the enrolment as unavailable.
- A passkey is bound for life to the **relying-party id**, which defaults to
  the host the request arrives on, without the port; the accepted origin
  defaults to the request's own. Behind a proxy that rewrites `Host`, or to
  keep serving keys enrolled under an earlier hostname, pin them:
  ```ini
  WEBAUTHN_RP_ID=grc.example.com
  WEBAUTHN_ORIGINS=https://grc.example.com
  WEBAUTHN_USER_VERIFICATION=preferred     # or required, to insist on a PIN/biometric
  ```

A key whose signature counter goes backwards is treated as cloned: it is
disabled and the sign-in refused, and the person needs their other factor.
`manage.py`-free recovery is an administrator's *Reset MFA* on the Users page,
which removes the authenticator app and every passkey.

On the local development servers the Vite proxy rewrites `Host` to the
backend's, so pin the relying party there too:
`WEBAUTHN_RP_ID=localhost` and `WEBAUTHN_ORIGINS=http://localhost:5173`.

### The questionnaire sent to the vendor

The link a vendor receives is built from `PUBLIC_URL`. With DEBUG off (the
Docker default, and any production install) `PUBLIC_URL` is required: until
it is set, sending is refused, because the link carries a bearer token and
must not point wherever the request said. Only in DEBUG (the local
development path) does an unset `PUBLIC_URL` fall back, to the sending
browser's origin when that origin is listed in `CSRF_TRUSTED_ORIGINS` or
`CORS_ALLOWED_ORIGINS`, and otherwise to the address the request arrived at. Set `PUBLIC_URL` in `.env`, with
`ORGANISATION_NAME` so the email says who is asking:
```ini
PUBLIC_URL=https://grc.example.com
ORGANISATION_NAME=Acme Ltd
```
Emails go out through whichever `EMAIL_PROVIDER` is configured; with
`console` (the default) the link is printed to the server log and shown
once on screen instead.

### Optional: scan uploaded evidence for malware

Put `CONFORMITI_SCANNING=true` in `.env` (it tells the API to use the
scanner), then start the stack with the scanning profile:

```bash
docker compose --profile scanning up -d          # also starts a ClamAV daemon
```

Pass `--profile scanning` to later `up` commands too, or put
`COMPOSE_PROFILES=scanning` in `.env`. The first start downloads the
signature database, which takes a few minutes; the container reports whether
the scanner answered. **Scanning fails closed**: while it is on and the daemon
is unreachable, uploads are refused rather than stored unscanned.

### Watching the malware scanner

With scanning on, `GET /api/health/` reports `scanning.reachable`, the worker
emails `COMPLIANCE_TEAM_EMAIL` once when clamd stops answering (uploads are
refused meanwhile) and once when it is back, and the tray tells
administrators. Signatures arrive after files do, so re-scan what is stored:

```bash
docker compose exec backend python manage.py scan_evidence --probe      # is clamd answering?
docker compose exec backend python manage.py scan_evidence              # files not scanned in 30 days
docker compose exec backend python manage.py scan_evidence --all        # everything
```

A file that now matches is quarantined: kept on disk, refused on every
route, badged in the document list, and in the audit trail. Exit code 1 on
an infection or an unreachable scanner, so cron can alert on it. A monthly
cron line is enough:

```
15 3 1 * *  cd /app && python manage.py scan_evidence --stale 30
```

### Package signing

Every sealed package manifest is signed with an Ed25519 key kept in a file
the compose stack generates on first use in the `secrets` volume
(`/app/secrets/package_signing_key`, 0600). Nothing to configure; **back the
volume up** with the database. The public key and its fingerprint are under
*Settings › About* and at `GET /api/signing-keys/`. Hand the fingerprint to
your auditors out of band so they can tell your key from a forger's. To use
a key you manage elsewhere, set `SIGNING_KEY` (PEM, or a base64 32-byte
seed). To rotate:

```bash
docker compose exec backend python manage.py rotate_signing_key --label FY27
```

The old key file is kept beside the new one, its public key stays published
as retired, and every package already sealed keeps verifying under the key it
carries. `SIGNING_ENABLED=false` seals packages unsigned, as before 0.7.0.

### Slack, Teams and digest emails

Create an incoming webhook in Slack (an app with *Incoming Webhooks*) or
Teams (the channel's *Workflows › Post to a channel when a webhook request is
received*), and set:

```ini
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/…
TEAMS_WEBHOOK_URL=https://….logic.azure.com/…
PUBLIC_URL=https://grc.example.com        # so each post links back
# NOTIFY_EVENTS=package.sealed,pbc.returned,scanner.down   # default: everything
```

An administrator can send a test message from *Settings › Notifications* and
see the last deliveries there. Digest emails need no configuration beyond a
working `EMAIL_PROVIDER`: each person switches theirs on under the same
section; the worker sends them at `REVIEW_SCAN_HOUR` + 20 minutes, or run
`manage.py send_digests` from cron.

Since 0.9.5 each workspace can carry its own Slack and Teams webhooks, set
by a superuser under *Settings › Role & access › Workspaces*. A workspace
with its own addresses posts only to them. The installation-wide addresses
above serve a single-workspace installation as before; once a second
workspace exists they are held back from every workspace, so one
organisation's package events never land in another's channel, unless
`WEBHOOKS_SHARED_ACROSS_WORKSPACES=true` says that is what you want.

### Workspaces

Since 0.9.0 every row belongs to a workspace; a fresh install and every
upgraded one start with a single workspace, `default`. To host a second
organisation, sign in as a superuser, open *Settings › Role & access* and
create it (the built-in roles are seeded, and the framework library unless
you untick it), switch to it and add its people under *Users*. A workspace can
only be created there; once it exists, seed and populate it from the shell:

```bash
docker compose exec backend python manage.py seed_frameworks --with-folders --workspace acme
docker compose exec backend python manage.py bootstrap_demo --workspace acme
```

Scheduled jobs walk every active workspace. `SSO_WORKSPACE` names the one
an auto-provisioned single-sign-on account joins. A workspace is archived
rather than deleted: its people are refused at sign-in and it drops out of
every job, and its rows stay where an operator can find them.

**Upgrading to 0.9.0** runs ten migrations that add the column, file every
existing row under *Default* and make the column required. Take a backup
first, as always.

### Sessions: cookies by default

Since 0.6.1 the SPA's tokens travel as HttpOnly cookies (`AUTH_TRANSPORT=cookie`),
with `__Host-` / `__Secure-` prefixes over https. Upgrading from 0.6.0 or
earlier signs everyone out once. Set `AUTH_TRANSPORT=header` to keep tokens in
`localStorage` as before. API clients using a Bearer header are unaffected.

**From 0.9.5i, signing in with cookies is CSRF-checked.** The check used to
run inside cookie authentication, which meant it only ever guarded a request
that already had a session, and the endpoints that hand out the cookies have
none by definition: a cross-site form post could sign a visitor's browser into
someone else's account. `/api/auth/token/`, `/api/auth/token/refresh/` and
`/api/auth/oidc/redeem/` now require `X-CSRFToken`, matching the readable
`csrftoken` cookie. The interface already worked this way. A script does this:

```bash
# 1. /api/auth/config/ sets the cookie, and says which transport is live.
curl -sc jar https://grc.example.com/api/auth/config/ >/dev/null
token=$(awk '$6 ~ /csrftoken$/ {print $7}' jar | tail -1)
# 2. Sign in with it. The token rotates here, so read the jar again afterwards.
curl -sb jar -c jar -H "X-CSRFToken: ${token}" \
     -H 'Content-Type: application/json' \
     -d '{"username":"…","password":"…"}' \
     https://grc.example.com/api/auth/token/
```

A Bearer client needs none of this: a header is not attached by a browser on
its own, so it cannot be forged cross-site. That is why the transport setting
does not change how integrations authenticate.

Everyday operations:

```bash
docker compose logs -f backend worker      # logs
docker compose pull && docker compose up -d --build   # update, built from source
docker compose exec backend python manage.py send_review_reminders --dry-run
docker compose down                        # stop (volumes are kept)
```

Update after `scripts/backup.sh` and a checkout of the new release
([README, Upgrading](README.md#upgrading)). An installation started from the
published images must keep the override on both commands (or carry
`COMPOSE_FILE` in `.env`, as *Without a build* shows): the plain update line
above would quietly switch it to building from source. Set
`CONFORMITI_VERSION` to the new release if you pin one:

```bash
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

---

## 2. Local development (SQLite, console email)

```bash
./install.sh                 # macOS / Linux / WSL
.\install.ps1                # Windows PowerShell
```

On Windows, if PowerShell refuses the script (*running scripts is disabled on
this system*), use `powershell -ExecutionPolicy Bypass -File .\install.ps1`;
§1's scripted variant explains the execution policy.

The installer verifies Python 3.11+ and Node 20.19+ or 22.12+, creates `.env`
with a generated secret key, builds `.venv`, installs backend and frontend
dependencies, applies migrations, seeds the control libraries, and starts the
API on **:8000** and the Vite dev server on **:5173** (`CONFORMITI_DEV_API_PORT`
and `CONFORMITI_DEV_PORT` move them: see *Moving the ports*). Every step is
exit-code checked; a failing step stops the installer.

No account exists yet. Create your first one (in a second terminal while the
servers run), then open **http://localhost:5173**. Its password must pass the
policy described in §1 (12 characters or more by default):

```bash
cd backend && ../.venv/bin/python manage.py createsuperuser
# Windows: cd backend; ..\.venv\Scripts\python.exe manage.py createsuperuser
```

To look around a worked example instead, run the installer with `--demo` /
`-Demo`. It loads the sample organisation, and the run that creates the demo
accounts prints their password in the seeding step's output (the line
starting `Sign in as`) and again in the closing *Setup complete* banner. A
re-run keeps the password, and the banner says it is unchanged. After
`remove_demo_data`, `--demo` / `-Demo` seeds nothing: the installer says the
demo was retired and prints the `manage.py bootstrap_demo --force` command
that seeds it again. The demo accounts all share one password:

| Username | Role |
|---|---|
| `admin` | Administrator (superuser) |
| `mia` | Compliance Manager |
| `owen` | Control Owner |
| `aria` | Auditor |
| `val` | Viewer |

Useful flags:

| Flag | Effect |
|---|---|
| `--setup-only` / `-SetupOnly` | install and seed, don't start servers |
| `--test` / `-Test` | run the validator, the backend test suite and a production frontend build |
| `--demo` / `-Demo` | also load the sample organisation and its five demo accounts |
| `--reset` / `-Reset` | wipe `db.sqlite3` and uploads and reseed, without starting the servers |
| `--no-demo` / `-NoDemo` | the default (no demo data); kept because older notes use it |
| `--open` / `-Open` | open the browser when ready |

Re-running the installer is safe: it reuses `.venv`, leaves `.env` alone, and
every seeder is idempotent.

Review reminders on this path run on demand:

```bash
cd backend
../.venv/bin/python manage.py send_review_reminders --dry-run    # Windows: ..\.venv\Scripts\python.exe
```

---

## 3. Manual / bare metal (Linux)

The examples assume the checkout is at `/srv/conformiti`, owned by a
`conformiti` system user; adjust both to taste.

Create the database role and the database; `createuser -P` asks for the
password that goes into `POSTGRES_PASSWORD` below:

```bash
sudo -u postgres createuser -P compliance
sudo -u postgres createdb -O compliance compliance
```

Copy the configuration with `cp .env.example .env` and set, in `.env`:

- `DJANGO_DEBUG=false` and a real `DJANGO_SECRET_KEY`
  (`python3 -c "import secrets; print(secrets.token_urlsafe(50))"`);
- `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS`
  for your hostname, as in §1's *Going to production*;
- `POSTGRES_DB=compliance`, `POSTGRES_USER=compliance`,
  `POSTGRES_PASSWORD` and `POSTGRES_HOST=localhost`. A non-empty
  `POSTGRES_DB` is what selects PostgreSQL; without it the app uses SQLite;
- nothing for the Celery broker if Redis runs on this machine:
  `.env.example` leaves `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`
  unset, and unset means `redis://localhost:6379/0` and `/1`. Set them only
  if your Redis is elsewhere. A `redis://redis:…` URL, which older copies of
  `.env.example` carried, names the Docker service and does not resolve here.
  With no Redis at all, run no Celery process and use the cron lines further
  down instead.

Then install, seed and start the API:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python manage.py migrate
python manage.py seed_frameworks --with-folders
python manage.py createsuperuser         # the password must pass the policy in §1
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

Run `celery -A config worker -l info` and, once and only once,
`celery -A config beat -l info` under a supervisor for the daily jobs (a
single worker may carry the scheduler itself with `-B`, but never more than
one). With systemd, three units do it. The application reads
`/srv/conformiti/.env` itself, so the units need no `EnvironmentFile`:

```ini
# /etc/systemd/system/conformiti-web.service
[Unit]
Description=Conformiti API (gunicorn)
After=network.target

[Service]
User=conformiti
WorkingDirectory=/srv/conformiti/backend
ExecStart=/srv/conformiti/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/conformiti-worker.service
[Unit]
Description=Conformiti Celery worker
After=network.target

[Service]
User=conformiti
WorkingDirectory=/srv/conformiti/backend
ExecStart=/srv/conformiti/.venv/bin/celery -A config worker -l info
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/conformiti-beat.service (the scheduler: one, ever)
[Unit]
Description=Conformiti Celery beat
After=network.target

[Service]
User=conformiti
WorkingDirectory=/srv/conformiti/backend
StateDirectory=conformiti
ExecStart=/srv/conformiti/.venv/bin/celery -A config beat -l info -s /var/lib/conformiti/celerybeat-schedule
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now conformiti-web conformiti-worker conformiti-beat
```

Or, with no broker, schedule the jobs with cron:

```
0 6 * * *  cd /srv/conformiti/backend && ../.venv/bin/python manage.py send_review_reminders
5 6 * * *  cd /srv/conformiti/backend && ../.venv/bin/python manage.py record_readiness
20 6 * * * cd /srv/conformiti/backend && ../.venv/bin/python manage.py send_digests
30 3 * * 0 cd /srv/conformiti/backend && ../.venv/bin/python manage.py flushexpiredtokens
```

Build the SPA once (`cd frontend && npm ci && npm run build`) and serve
`frontend/dist` with the shipped `frontend/nginx.conf` as a template (it
proxies `/api/` and `/admin/` to gunicorn and serves `/media/` and `/static/`
from disk).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| The backend log says `DJANGO_SECRET_KEY must be set…` | Docker: the stack reads `CONFORMITI_SECRET_KEY`, never `DJANGO_SECRET_KEY` or `DJANGO_DEBUG`, and this means `CONFORMITI_SECRET_KEY` is set to something shorter than 32 characters. Delete the line (the container generates and keeps its own key) or set a longer one. Bare metal: `DJANGO_DEBUG=false` with the placeholder key from `.env.example` and no `DJANGO_SECRET_KEY_FILE`; set a real key. |
| The app loads but every request is `400 Bad Request` | The hostname you browse with isn't in `DJANGO_ALLOWED_HOSTS`. |
| Admin login form reloads silently over plain HTTP | `BEHIND_TLS=true` (secure cookies) on an HTTP deployment. Set it to `false` until TLS is in front. |
| `/api/health/` says `"database": "unavailable"` | PostgreSQL is not up, or the credentials differ between the `db` and `backend` services. The usual cause is `POSTGRES_PASSWORD` changed in `.env` after the first boot: the database volume keeps the password it was created with. Put the old value back, or change it in the database as §1 *Going to production* step 1 shows, then `docker compose up -d` (with the same `-f` files you started with). |
| Login always fails on the local path | No account exists: `cd backend && ../.venv/bin/python manage.py createsuperuser` (the password must pass the policy in §1), or seed the sample data with `manage.py bootstrap_demo`. Or the web app runs on a port or host name missing from `CSRF_TRUSTED_ORIGINS` in `.env` (see *Moving the ports*). |
| `Too many attempts` at sign-in | The per-client login throttle (8/min). Wait a minute. |
| Uploads rejected as too large | Raise `MAX_UPLOAD_MB` **and** `client_max_body_size` in `frontend/nginx.conf`. |
| Port in use | Docker needs host ports 8080 (`CONFORMITI_PORT`) and `127.0.0.1:8000` (`CONFORMITI_API_PORT`); the local path needs 8000 and 5173 (`CONFORMITI_DEV_API_PORT`, `CONFORMITI_DEV_PORT`). Every one of them can move, but a moved web port also needs its origin in `.env`: see *Moving the ports* below. |

<details>
<summary><strong>Moving the ports</strong></summary>

**Docker.** nginx publishes host port 8080 (`CONFORMITI_PORT`), and the API
publishes `127.0.0.1:8000` for debugging (`CONFORMITI_API_PORT`). Both must be
free, and `CONFORMITI_PORT` does not move the API. Set whichever clashes in
`.env`, and make the origin lists follow the nginx port, or sign-in is
refused (with no lists in `.env`, the stack trusts `:8080` only):

```ini
CONFORMITI_PORT=8081
CONFORMITI_API_PORT=8001
CSRF_TRUSTED_ORIGINS=http://localhost:8081,http://127.0.0.1:8081
CORS_ALLOWED_ORIGINS=http://localhost:8081
```

The scripted variant's `--port N` / `-Port N` writes the nginx port and both
lists into a new `.env`, or moves them in an existing one. If
`docker compose up` stopped on a bind error, free the port and run
`docker compose up -d --force-recreate backend`, with the same `-f` files you
started with: a backend container that failed to publish its port can be left
without a network.

**Local development.** It has two variables of its own and never reads the
Docker ones: `CONFORMITI_DEV_API_PORT` (default 8000) is where `runserver`
listens and where the Vite dev server proxies `/api/` and `/media/`, and
`CONFORMITI_DEV_PORT` (default 5173) is the dev server's own port. Both are
read from the shell, not from `.env`. Set them before running the installer
and it starts both servers on them, or start the servers by hand, giving
`runserver` the same API port on its command line:

```bash
cd backend && ../.venv/bin/python manage.py runserver 127.0.0.1:8001                 # first terminal
cd frontend && CONFORMITI_DEV_API_PORT=8001 CONFORMITI_DEV_PORT=5174 npm run dev     # second terminal
```

In PowerShell, set them first in the second window:
`$env:CONFORMITI_DEV_API_PORT=8001; $env:CONFORMITI_DEV_PORT=5174; npm run dev`.
(The end-to-end suite points the proxy at its own backend with
`E2E_API_PORT`, which wins over `CONFORMITI_DEV_API_PORT`.)
The dev server stops rather than moving when its port is taken. A web app on
a new port or host name is a new origin: add it (`http://localhost:5174`
here) to `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` in `.env` and
restart `runserver`, or every sign-in is refused, and move a pinned
`WEBAUTHN_ORIGINS` with it. Browse `http://localhost:…`, not `127.0.0.1`:
Vite listens on `localhost`, and `.env` trusts only that name.
</details>

<details>
<summary><strong>The site loads but I cannot sign in</strong></summary>

Almost always `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` or
`CORS_ALLOWED_ORIGINS` not listing the hostname you are actually using,
including scheme and port. The backend log names the header it rejected. Behind
a proxy, confirm it forwards `Host` and `X-Forwarded-Proto`.
</details>

<details>
<summary><strong>Downloads fail, or the browser refuses the file</strong></summary>

Check that nothing adds a `Content-Disposition` header in the
`/protected-media/` nginx location. Django sets it upstream and nginx passes it
through; adding one produces two headers, and browsers refuse the response.
</details>

<details>
<summary><strong>Passkeys will not enrol or verify</strong></summary>

`WEBAUTHN_RP_ID` must be a domain name: browsers refuse an IP address,
including `127.0.0.1`. Use `localhost` for local work and set
`WEBAUTHN_ORIGINS` to match exactly, port included. If a proxy rewrites `Host`,
pin both values rather than letting them be derived.
</details>

<details>
<summary><strong>Reminder emails are not arriving</strong></summary>

`manage.py send_review_reminders --dry-run` shows what the scan believes is
due. To test the transport separately,
`manage.py test_mailbox --to you@example.com` sends a sample review reminder
through whichever `EMAIL_PROVIDER` is configured, with the template and
transport real reminders use (`console` prints it in the command's output
and delivers nothing). With `mailbox` it first signs in to the account over
IMAP or POP3 and stops there if that fails; without `--to`, that sign-in is
all it does. Each lead window
is sent once and recorded on the document, so a second run will not re-send
yesterday's mail, which is correct and often mistaken for a failure.
</details>

<details>
<summary><strong>Everything returns 403 after upgrading to 0.9.0</strong></summary>

An account with no workspace cannot make API requests. A superuser created by
`createsuperuser` lands in the first active workspace automatically; anyone
else in that position is refused with 403 by design. Assign the account a
workspace under *Settings › Role & access*, or re-run the migration if it did
not complete.
</details>

<details>
<summary><strong>A file is stuck in quarantine</strong></summary>

The re-scan sweep quarantines a stored file when updated definitions match it.
That is intended, and the file is not deleted. Check the scanner status row and
the notification; if it is a false positive the file can be released, and the
release is an audit-log entry with your name on it.
</details>

<details>
<summary><strong>A PDF renders blank</strong></summary>

Do not add a `sandbox` attribute to the PDF frame: Chromium disables plugins
and renders blank. PDFs are drawn by pdf.js onto canvases; the viewer must
fetch through the API client and render from a blob, never point a frame at the
media URL.
</details>
