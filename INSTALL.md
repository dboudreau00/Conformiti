# Install

Three ways to run Conformiti, from "just show me" to production.

| Path | Best for | Needs | Command |
|---|---|---|---|
| **Docker** | evaluating, LAN pilots, production | Docker Engine 24+ / Docker Desktop with Compose 2.24 or newer | `docker compose up -d --build` |
| **Local dev** | hacking on the code | Python 3.11 to 3.14 with `venv` and `pip`, Node 20.19+ or 22.12+ | `./install.sh`, or on Windows `powershell -ExecutionPolicy Bypass -File .\install.ps1` |
| **Manual** | custom hosting, bare metal (Linux) | as above + PostgreSQL, Redis, nginx | see §3 |

Every path starts with `git clone` and a checkout of the newest release tag
(`main` is the development line, and installs and upgrades follow release
tags), so you need git as well, and `./install.sh --docker` needs curl to
wait for the stack. On Debian and Ubuntu Python's `venv` module is a separate
package:
`sudo apt install python3-venv python3-pip`. The full list is in
[PREREQUISITES.md](PREREQUISITES.md).

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
git checkout "$(git tag --list 'v*' --sort=-v:refname | head -n1)"   # the newest release
docker compose up -d --build
```

The third line checks out the newest release and leaves the checkout on a
detached HEAD, which is intended ([README, Upgrading](README.md#upgrading)).
In PowerShell it reads
`git checkout (git tag --list 'v*' --sort=-v:refname | Select-Object -First 1)`.

Then create the first account with
`docker compose exec backend python manage.py createsuperuser` (the sign-in
page cannot make one), open **http://localhost:8080** and sign in with it.
Its password must pass the same policy as every other account's: at least
`PASSWORD_MIN_LENGTH` characters (12 by default), not a common password, not
all digits, and not too close to the username or email. The policy has no
bypass: `createsuperuser` refuses a password that fails it, says why and asks
for another.

To look around a worked example instead, put `SEED_DEMO_DATA=true` in `.env`
(create the file if there is none) before you run `docker compose up`, or use
`--demo` with the scripted variant below. That seeds five accounts sharing one
password, generated on first boot and printed once
(`docker compose logs backend | grep "Sign in as"`, or set `DEMO_PASSWORD` in
`.env` beforehand). Note it when you see it: the log keeps it only until the
backend container is recreated, which `docker compose up` does after any
change to `.env`. It is off by default: an installation carrying those
accounts says so on its own sign-in page, which is not a thing a real
deployment should publish.

Keep settings like these in `.env`. Compose reads that file on every start
and hands it to the application containers; a variable exported in your
shell is seen only by commands run from that shell, and only for the keys
`docker-compose.yml` passes through.

What happens on first boot:

1. PostgreSQL 16 and Redis 7 start with healthchecks.
2. The API container waits for the database, applies the shipped migrations,
   seeds the three control libraries (217 controls, and 249 folders in the
   app's document tree, one per framework, category and control: the boot
   log says `App folders created: 249`) and the built-in roles, seeds the
   demo dataset only if you asked for it (`SEED_DEMO_DATA=true`), writes the
   evidence tree on disk (1,117 folders: those 249, plus `policies`,
   `procedures`, `evidence` and `forms` under each control), collects static
   files and starts gunicorn as an unprivileged user.
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
./install.sh --docker                                            # macOS / Linux / WSL
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Docker   # Windows
```

The script checks Docker is running, writes a production-style `.env` if you
don't have one (DEBUG off, your hostname in `DJANGO_ALLOWED_HOSTS`, the
origin lists for its port, and no secret key: the container generates its
own and keeps it in the `secrets` volume, as on the plain path above),
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
password, which it reads from `docker compose logs backend`, marked
*note it now*: the password is logged once, by the container that created
the accounts, and recreating that container starts a log without it. An
upgrade recreates it, and so does any change to `.env`, the ones `--port`,
`--demo` and `--no-demo` write included. From then on the banner says so and
gives the command that sets a new one:
`docker compose exec backend python manage.py changepassword admin`.
Without demo accounts, the banner reads the same health report: while the
installation has no active account it gives the `createsuperuser` command for
your first one, and once one exists it says to sign in with it.

The banner's *Rebuild* line re-runs the script, which builds and starts
whatever is checked out and nothing more. An upgrade is a backup and a
checkout of the new release tag first, then that rebuild; its *Upgrade* line
points at [README, Upgrading](README.md#upgrading), which has the commands.

**Windows PowerShell and the execution policy.** On a default Windows 10 or 11
client, Windows PowerShell 5.1 refuses every script with *running scripts is
disabled on this system*. That is why the Windows line above starts the
installer with a bypass: it lasts only for that one process and changes no
setting. Alternatively, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once in the
window, then `.\install.ps1 -Docker` as usual. PowerShell 7 (`pwsh`) runs local
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
export CONFORMITI_VERSION=0.9.5m
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
CONFORMITI_VERSION=0.9.5m
```

Keep the pin there too. The `export` above lasts for that shell, and a
version given inline (`CONFORMITI_VERSION=0.9.5m docker compose ...`) for
that one command. While the export lasts it overrides `.env`, so once the pin
is written there, run `unset CONFORMITI_VERSION` and keep the variable out of
shell profiles: the pin in `.env` is then the one every later command reads,
`scripts/restore.sh` included. An upgrade moves it there
([README, Upgrading](README.md#upgrading)), and an exported value left
behind would keep that shell on the old release.

Separate the two files with `;` instead of `:` when you run Docker Desktop's
Windows `docker.exe` rather than Docker inside WSL 2. Keep one `COMPOSE_FILE`
line in `.env`: when there are two, Compose uses the last one and ignores the
other, so extend the existing line rather than adding a new one.

nginx's configuration is the one part of this path that does not come from
the checkout. It is built into the frontend image, so editing
`frontend/nginx.conf` changes nothing here. To run an edited copy (a larger
`client_max_body_size`, say), mount it from a third compose file of your own,
for example `docker-compose.nginx.yml`:

```yaml
services:
  frontend:
    volumes:
      - ./frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

Name it after the other two, on every command or once in `.env`
(`COMPOSE_FILE=docker-compose.yml:docker-compose.ghcr.yml:docker-compose.nginx.yml`),
and run `up -d`. After a later edit, `docker compose restart frontend` makes
nginx read the file again.

A container will tell you what it is: `curl -s localhost:8080/api/health/`
reports the version compiled into the image, and
`docker inspect ghcr.io/dboudreau00/conformiti-backend:0.9.5m` carries the
commit it was built from in `org.opencontainers.image.revision`.

Building from source remains the default, and stays supported: the images are
built from the same two Dockerfiles in this repository, by a workflow that
pulls what it pushed and boots it before the run is allowed to pass.

### Going to production

1. Set the real hostname in `.env`:
   ```ini
   DJANGO_ALLOWED_HOSTS=grc.example.com      # your public host name(s)
   CSRF_TRUSTED_ORIGINS=https://grc.example.com
   CORS_ALLOWED_ORIGINS=https://grc.example.com
   BEHIND_TLS=true            # once TLS is terminated in front of nginx
   NUM_PROXIES=2              # the terminator AND the shipped nginx
   SECURE_HSTS_SECONDS=31536000
   EMAIL_PROVIDER=smtp        # + EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD
   POSTGRES_PASSWORD=<something long>
   REDIS_PASSWORD=<letters and digits>
   ```
   `DJANGO_ALLOWED_HOSTS` is your public host name(s), comma-separated; the
   Docker stack adds its own internal names (`localhost`, `127.0.0.1` and
   `backend`) itself, so you need not list those, and its healthcheck keeps
   working whatever you write here.

   `NUM_PROXIES` is how many hops back along `X-Forwarded-For` the client's
   address is. The default of 1 is the shipped nginx on its own. Put a TLS
   terminator in front of it, which is the next step, and there are two:
   leaving it at 1 makes the terminator's address every visitor's address, so
   they share one rate-limit bucket and a single unauthenticated caller can
   spend the installation's login budget for everybody. Two is right whether
   your terminator appends to `X-Forwarded-For` or replaces it: the shipped
   nginx appends the address it received the request from, the terminator's,
   so the client's is two entries from the end either way. The stack warns at
   boot if `BEHIND_TLS` is on and `NUM_PROXIES` is not set. (On bare metal,
   where the host's own nginx terminates TLS, there is one hop: see §3.)

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
   `CONFORMITI_VERSION` (the backup's release) in `.env`, and none exported
   in the shell that runs it (an exported value overrides `.env`), as
   *Without a build* shows: the script takes no `-f` files, without `COMPOSE_FILE` it
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
`manage.py`-free recovery is an administrator's *Reset 2FA* on the Users page
(its confirmation reads *Reset two-factor*), which removes the authenticator
app, every passkey and the backup codes.

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
line in the host's crontab is enough (use your checkout's path; `-T`
because cron gives the command no terminal):

```
15 3 1 * *  cd /path/to/Conformiti && docker compose exec -T backend python manage.py scan_evidence --stale 30
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
docker compose pull && docker compose up -d --build   # rebuild what is checked out
docker compose exec backend python manage.py send_review_reminders --dry-run
docker compose down                        # stop (volumes are kept)
```

The rebuild line is an upgrade only after `scripts/backup.sh` and a checkout
of the new release tag ([README, Upgrading](README.md#upgrading)). An
installation started from the published images must keep the override on
both commands (or carry `COMPOSE_FILE` in `.env`, as *Without a build*
shows): the plain line above would quietly switch it to building from
source. If you pin `CONFORMITI_VERSION`, set it in `.env` to the new release:
an inline or exported value lasts only for that command or shell, and the
next short-form command goes back to the pin in `.env`. An exported value
also overrides `.env` for as long as it lasts, so `unset CONFORMITI_VERSION`
before the upgrade.

```bash
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

---

## 2. Local development (SQLite, console email)

```bash
./install.sh                                          # macOS / Linux / WSL
powershell -ExecutionPolicy Bypass -File .\install.ps1   # Windows
```

On Windows the bypass is what lets the script run where the default policy
refuses it (*running scripts is disabled on this system*); it lasts for that
one run and changes no setting. §1's scripted variant explains the execution
policy. For a trial, run it from a checkout of the newest release tag, as §1
shows; to work on the code, from a branch of `main`
([CONTRIBUTING.md](CONTRIBUTING.md)).

The installer checks for Python 3.11 or newer (3.11 to 3.14 are the tested
versions; it warns above them) and Node 20.19+ or 22.12+. On Debian and
Ubuntu, install Python's `venv` module first
(`sudo apt install python3-venv python3-pip`): without it `.venv` cannot be
created. The `nodejs` package of Debian 12 and Ubuntu 24.04 (18) or Ubuntu
22.04 (12) is too old, and the installer stops on it: install Node 22 LTS
from NodeSource's repository (§3 shows the commands) or with nvm, and check
`node --version`. Other requirements are in
[PREREQUISITES.md](PREREQUISITES.md). The
installer then creates `.env` with a generated secret key, builds `.venv`,
installs backend and frontend
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

Re-running the installer is safe: it reuses `.venv` (a `.venv` without a
working pip, which a creation that stopped part way leaves behind, is deleted
and built again), leaves `.env` alone, and every seeder is idempotent. It
also keeps `frontend/node_modules` when that already matches
`package-lock.json`, so a re-run or `--test` of an unchanged checkout does not
pull the packages out from under a dev server that is still running. On
Windows, where a running dev server holds files npm would have to replace, a
reinstall is refused while the dev server's port is served: close the two
server windows first.

Review reminders on this path run on demand:

```bash
cd backend
../.venv/bin/python manage.py send_review_reminders --dry-run    # Windows: ..\.venv\Scripts\python.exe
```

---

## 3. Manual / bare metal (Linux)

The examples assume the checkout is at `/srv/conformiti`, owned by a
`conformiti` system user; adjust both to taste. The host needs PostgreSQL 16,
Redis 7, nginx, git, curl (for the NodeSource step below), Python 3.11 to
3.14 with `venv` and `pip`, and Node 20.19+ or 22.12+ to build the interface.

- **PostgreSQL 16** is what the Docker stack runs and CI tests. Django 5.2
  itself refuses anything older than 14, and 14 and 15 are not tested here.
  Ubuntu 24.04 ships 16; Debian 12 ships 15 and Ubuntu 22.04 ships 14, so on
  those add the PostgreSQL project's repository first (its script asks for
  Enter before it writes anything):
  ```bash
  sudo apt install postgresql-common gnupg
  sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
  sudo apt install postgresql-16
  ```
- **Node**: the distributions' own `nodejs` packages are usually too old for
  the build (Debian 12 and Ubuntu 24.04 ship 18, Ubuntu 22.04 ships 12).
  Install Node 22 LTS from NodeSource's repository instead (curl first, which
  minimal systems lack), then check `node --version`:
  ```bash
  sudo apt install curl ca-certificates
  curl -fsSL https://deb.nodesource.com/setup_22.x -o nodesource_setup.sh
  sudo bash nodesource_setup.sh
  sudo apt install nodejs
  ```

Create the user with a home directory, and the checkout as that user:

```bash
sudo useradd --system --user-group --create-home --shell /usr/sbin/nologin conformiti
sudo install -d -o conformiti -g conformiti /srv/conformiti
sudo -u conformiti -H git -C /srv/conformiti clone https://github.com/dboudreau00/Conformiti.git .
```

The home directory is for npm, which keeps its cache there: `npm ci` stops
with a permission error under a system user made without one
(`useradd --system` alone creates none, and `adduser --system` on Debian 12
or Ubuntu 24.04 points it at `/nonexistent`). A `conformiti` user that
already exists gets one with
`sudo install -d -o conformiti -g "$(id -gn conformiti)" /home/conformiti` and
`sudo usermod -d /home/conformiti conformiti` (`id -gn` names the group the
user really has: `adduser --system` puts it in `nogroup`, not a `conformiti`
group).

Run every command below that works in the checkout as that user
(`sudo -u conformiti -H bash`, then `cd /srv/conformiti`), so the files they
create belong to the account the services run as. Some of those files are
keys the application writes at mode 0600, and a copy owned by root is one the
services cannot read. Only the `sudo` lines (the user above, the database,
systemd) and the nginx configuration need root.

The first of them checks out the newest release, since `main` is the
development line:

```bash
git checkout "$(git tag --list 'v*' --sort=-v:refname | head -n1)"
```

Create the database role and the database; `createuser -P` asks for the
password that goes into `POSTGRES_PASSWORD` below:

```bash
sudo -u postgres createuser -P compliance
sudo -u postgres createdb -O compliance compliance
```

Copy the configuration and make it readable by the `conformiti` account
alone. It will hold `DJANGO_SECRET_KEY`, which also signs the sign-in tokens,
and `POSTGRES_PASSWORD`; `cp` leaves it readable by every account on the
host, nginx's included:

```bash
cp .env.example .env && chmod 600 .env
```

Then set, in `.env`:

- `DJANGO_DEBUG=false` and a real `DJANGO_SECRET_KEY`
  (`python3 -c "import secrets; print(secrets.token_urlsafe(50))"`);
- `DJANGO_FIELD_ENCRYPTION_KEY_FILE=/srv/conformiti/backend/.field-encryption-key`,
  before the first `manage.py` command. The file is generated there at mode
  0600 and holds the key that encrypts enrolled authenticators at rest.
  Without it that key is derived from `DJANGO_SECRET_KEY`, which ties the two
  together (see *Backups on bare metal* below);
- `DJANGO_ALLOWED_HOSTS` (your public host name(s)), `CSRF_TRUSTED_ORIGINS`,
  `CORS_ALLOWED_ORIGINS` and `PUBLIC_URL` for your hostname, as in §1's
  *Going to production*. Nothing adds `localhost` here the way the Docker
  stack does, so list it too if you query the API on this machine;
- `POSTGRES_DB=compliance`, `POSTGRES_USER=compliance`,
  `POSTGRES_PASSWORD` and `POSTGRES_HOST=localhost`. A non-empty
  `POSTGRES_DB` is what selects PostgreSQL; without it the app uses SQLite;
- nothing for the Celery broker if Redis runs on this machine:
  `.env.example` leaves `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`
  unset, and unset means `redis://localhost:6379/0` and `/1`. Set them only
  if your Redis is elsewhere. A `redis://redis:…` URL, which older copies of
  `.env.example` carried, names the Docker service and does not resolve here.
  With no Redis at all, run no Celery process and use the cron lines further
  down instead;
- `CACHE_URL=redis://localhost:6379/2` (`redis://:<password>@localhost:6379/2`
  if your Redis asks for one). The rate limits, the login throttle among
  them, count in this cache. Left unset, each gunicorn worker keeps its own
  count in memory, so with the three workers below an attacker gets three
  times `THROTTLE_LOGIN` before anything is refused, and the API warns about
  it at every start;
- `BEHIND_TLS=false` while the site is served over plain http (a trial on
  `http://localhost`). With `DJANGO_DEBUG=false` it defaults to on, which
  means secure cookies and every http request redirected to https. Remove
  the line, or set `true`, once TLS is in front;
- `NUM_PROXIES`, the number of proxies in front of gunicorn, which is what
  the rate limits use to find the client's address: `1` when this host's
  nginx faces the clients and terminates TLS itself, `2` when a separate TLS
  terminator or load balancer sits in front of that nginx. Unset means 1,
  and with `BEHIND_TLS` on the API warns at boot until you set it;
- nothing for `MEDIA_INTERNAL` behind nginx. With `DJANGO_DEBUG=false` it is
  on: the API checks access, writes the audit row and hands the download to
  nginx with an `X-Accel-Redirect`. Behind any other web server (Caddy,
  Apache, IIS) set `MEDIA_INTERNAL=false`, so Django sends the file itself;
  that header is nginx's, and elsewhere every download and preview arrives
  empty.

Then install, seed and start the API:

```bash
cd /srv/conformiti
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python manage.py migrate
python manage.py seed_frameworks --with-folders
python manage.py generate_folder_tree    # the evidence tree on disk, at COMPLIANCE_TREE_ROOT
python manage.py createsuperuser         # the password must pass the policy in §1
python manage.py collectstatic --noinput
mkdir -p media                           # MEDIA_ROOT; nothing creates it before the first upload
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

`generate_folder_tree` is what the Docker stack and the installers run after
seeding. With the default `COMPLIANCE_TREE_ROOT` (`compliance-data/` at the
top of the checkout) the clone already carries that tree and the command
leaves it as it is; a tree root set anywhere else starts empty without it.
`mkdir -p media` matters when `MEDIA_ROOT` is left at its default:
`backend/media` does not exist until the first upload, and the backup below
would otherwise report it missing and exit with status 2 (it still archives
everything else).

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

Or, with no broker, schedule the jobs in the `conformiti` user's crontab
(`sudo crontab -u conformiti -e`):

```
0 6 * * *  cd /srv/conformiti/backend && ../.venv/bin/python manage.py send_review_reminders
5 6 * * *  cd /srv/conformiti/backend && ../.venv/bin/python manage.py record_readiness
20 6 * * * cd /srv/conformiti/backend && ../.venv/bin/python manage.py send_digests
30 3 * * 0 cd /srv/conformiti/backend && ../.venv/bin/python manage.py flushexpiredtokens
```

Build the SPA once (`cd /srv/conformiti/frontend && npm ci && npm run build`)
and serve it with nginx, taking the shipped `frontend/nginx.conf` as the
template. It proxies `/api/` and `/admin/`, serves `/static/`, and sends
evidence only from an `internal` location the API redirects into. It is
written for the Docker stack, so change these for this host:

- `server_name _;` to your host name (`server_name grc.example.com;`). On
  Debian and Ubuntu the distribution's own site,
  `/etc/nginx/sites-enabled/default`, is the `default_server` on port 80: it
  answers every request whose `Host` names no other server, and `_` names
  none, so the browser gets *Welcome to nginx!* instead of Conformiti. Remove
  that link (`sudo rm /etc/nginx/sites-enabled/default`) unless it serves
  something else;
- `root` to `/srv/conformiti/frontend/dist`;
- both `proxy_pass http://backend:8000;` lines to `proxy_pass http://127.0.0.1:8000;`;
- the `/static/` alias to `/srv/conformiti/backend/staticfiles/`, where
  `collectstatic` put the admin's files;
- the `/protected-media/` and `/media/` aliases to your `MEDIA_ROOT`, trailing
  slash included: `/srv/conformiti/backend/media/` unless you set
  `MEDIA_ROOT`. Keep both locations `internal`. A wrong alias turns every
  download and preview into a 404;
- if this nginx terminates TLS itself (the case `NUM_PROXIES=1` above
  describes): the template's `listen 80;` gives way to a 443 listener with
  your certificate, plus a second `server` block on port 80 that only
  redirects to https (both shown below), and in the `/api/` and `/admin/`
  locations `proxy_set_header X-Forwarded-Proto $scheme;` replaces the
  `$forwarded_proto` line. The template passes on the header it received,
  which is right only behind a terminator that sets it, and with
  `BEHIND_TLS` on the API believes that header. With a separate terminator
  in front of this nginx instead, keep `listen 80;` and the header as they
  are.

```nginx
server {
    listen 80;
    server_name grc.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name grc.example.com;
    ssl_certificate     /etc/letsencrypt/live/grc.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/grc.example.com/privkey.pem;
    # ...then the template's server block from `root` down, edited as above
}
```

Use your own certificate's paths (those are certbot's), and add a
`listen [::]:80;` and `listen [::]:443 ssl;` line if clients reach the host
over IPv6.

Install the edited copy as a whole file in `/etc/nginx/conf.d/`, with a name
ending in `.conf` (`conformiti.conf`, say): its `map` block sits outside the
`server` block, where only a file nginx reads at the `http` level may put it.
Check it and load it with `sudo nginx -t && sudo systemctl reload nginx`.
nginx's own user must be able to read `frontend/dist`,
`backend/staticfiles` and `backend/media` (and pass through the directories
above them); it never needs the key files.

### Backups on bare metal

`scripts/backup.sh` and `scripts/restore.sh` drive the Docker stack's
containers and volumes, so they do not apply here. Back up these together,
and copy them off the machine:

| What | Where, in this recipe | Why |
|---|---|---|
| The database | `pg_dump` of `compliance` | everything but the files |
| The evidence files | `MEDIA_ROOT`: `/srv/conformiti/backend/media/` | a database without them is a list of files you no longer have |
| The folder tree on disk | `COMPLIANCE_TREE_ROOT`: `/srv/conformiti/compliance-data/` | the evidence tree generated from the control libraries |
| The package-signing key | `/srv/conformiti/backend/.package-signing-key`, and each `.package-signing-key.retired-*` beside it (`SIGNING_KEY_FILE` moves them) | signatures already issued stay valid without it, but you cannot sign as the same identity again |
| The field-encryption key | the file `DJANGO_FIELD_ENCRYPTION_KEY_FILE` names: `/srv/conformiti/backend/.field-encryption-key` | without it enrolled authenticators cannot be read (backup codes still work) and a stored Jira token must be entered again |
| `.env` | `/srv/conformiti/.env` | `DJANGO_SECRET_KEY` and the passwords |

For example, as root from cron. `tar` names any path that does not exist,
archives the rest and exits with status 2, which a cron wrapper reports as a
failed backup. The field-encryption key file is missing when you left the
setting unset (drop it from the line then), and `backend/media` on an
installation that skipped the `mkdir -p media` above and has had no upload
yet (create it, as the `conformiti` user):

```bash
mkdir -p /var/backups/conformiti
sudo -u postgres pg_dump -Fc compliance > /var/backups/conformiti/db-$(date +%F).dump
cd /srv/conformiti && tar -czf /var/backups/conformiti/files-$(date +%F).tgz \
    .env backend/media compliance-data backend/.field-encryption-key backend/.package-signing-key*
```

In a crontab line itself, write each `%` as `\%`: cron reads a bare one as
the end of the command.

To restore, stop the three services, reload the database with
`sudo -u postgres pg_restore --clean --if-exists -d compliance <dump>`, unpack
the files into `/srv/conformiti` (as the `conformiti` user, or `chown` them
back to it), make sure the restored `.env` is the `conformiti` user's at mode
0600 again (`chmod 600 .env`: an archive made before that step was in this
recipe carries it readable by everyone), and start the services again.

**The field-encryption key and `DJANGO_SECRET_KEY`.** With
`DJANGO_FIELD_ENCRYPTION_KEY_FILE` unset and a real `DJANGO_SECRET_KEY`, the
key ring is derived from `DJANGO_SECRET_KEY`. Changing that key then makes
every enrolled authenticator unreadable. Move the ring to a file before you
ever rotate it:

1. Write a file owned by `conformiti` at mode 0600 whose first line is a new
   key (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`) and
   whose second line is `derived:` followed by your current
   `DJANGO_SECRET_KEY`. Point `DJANGO_FIELD_ENCRYPTION_KEY_FILE` at it and
   restart the three services: both keys decrypt, the first one encrypts.
2. Run `manage.py rotate_field_keys` to rewrite every encrypted value under the
   new key, and `manage.py rotate_field_keys --status` to see that no row is
   left on the old one.
3. Delete the second line, restart, and only then change
   `DJANGO_SECRET_KEY` (which also signs everyone out).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| The backend log says `DJANGO_SECRET_KEY must be set…` | Docker: the stack reads `CONFORMITI_SECRET_KEY`, never `DJANGO_SECRET_KEY` or `DJANGO_DEBUG`, and this means `CONFORMITI_SECRET_KEY` is set to something shorter than 32 characters. Delete the line (the container generates and keeps its own key) or set a longer one. Bare metal: `DJANGO_DEBUG=false` with the placeholder key from `.env.example` and no `DJANGO_SECRET_KEY_FILE`; set a real key. |
| The app loads but every request is `400 Bad Request` | The hostname you browse with isn't in `DJANGO_ALLOWED_HOSTS`. |
| Admin login form reloads silently over plain HTTP | `BEHIND_TLS=true` (secure cookies) on an HTTP deployment. Set it to `false` until TLS is in front. |
| Every `/api/` request answers `301` to `https://` (bare metal, plain http) | With `DJANGO_DEBUG=false`, `BEHIND_TLS` is on unless `.env` says otherwise. Set `BEHIND_TLS=false` until TLS is in front (§3). |
| Downloads and previews arrive empty (bare metal) | `MEDIA_INTERNAL` is on and the web server in front is not nginx, so nothing acts on the API's `X-Accel-Redirect`. Set `MEDIA_INTERNAL=false` (§3). Behind nginx, a download that is a 404 means the `/protected-media/` alias does not point at `MEDIA_ROOT`. |
| `/api/health/` says `"database": "unavailable"` | PostgreSQL is not up, or the credentials differ between the `db` and `backend` services. The usual cause is `POSTGRES_PASSWORD` changed in `.env` after the first boot: the database volume keeps the password it was created with. Put the old value back, or change it in the database as §1 *Going to production* step 1 shows, then `docker compose up -d` (with the same `-f` files you started with). |
| Login always fails on the local path | No account exists: `cd backend && ../.venv/bin/python manage.py createsuperuser` (the password must pass the policy in §1), or seed the sample data with `manage.py bootstrap_demo`. Or the web app runs on a port or host name missing from `CSRF_TRUSTED_ORIGINS` in `.env` (see *Moving the ports*). |
| `Too many attempts` at sign-in | The per-client login throttle (8/min). Wait a minute. |
| Uploads rejected as too large | Raise `MAX_UPLOAD_MB` in `.env` **and** `client_max_body_size` in `frontend/nginx.conf`. nginx's configuration is built into the frontend image: after the edit, a source build needs `docker compose up -d --build`, and the published images need the edited file mounted (*Without a build*, above). `frontend/nginx.conf` is a tracked file, so the edit has to be set aside for each upgrade's `git checkout` ([README, Upgrading](README.md#upgrading)). Bare metal: edit your own copy and reload nginx. |
| Port in use | Docker needs host ports 8080 (`CONFORMITI_PORT`) and `127.0.0.1:8000` (`CONFORMITI_API_PORT`); the local path needs 8000 and 5173 (`CONFORMITI_DEV_API_PORT`, `CONFORMITI_DEV_PORT`). Every one of them can move: see *Moving the ports* below. |

<details>
<summary><strong>Moving the ports</strong></summary>

**Docker.** nginx publishes host port 8080 (`CONFORMITI_PORT`), and the API
publishes `127.0.0.1:8000` for debugging (`CONFORMITI_API_PORT`). Both must be
free, and `CONFORMITI_PORT` does not move the API. Set whichever clashes in
`.env`:

```ini
CONFORMITI_PORT=8081
CONFORMITI_API_PORT=8001
```

That is enough to sign in at `http://localhost:8081`. nginx hands the API the
`Host` header the browser sent, port included, and a sign-in from the same
scheme, host and port the request arrived at passes the origin check without
being listed. The origin lists matter when something in front of nginx
changes what the API sees (a reverse proxy that rewrites `Host`, or TLS
terminated in front without `BEHIND_TLS=true`), and a new host name also
needs `DJANGO_ALLOWED_HOSTS`. Listing the moved origin does no harm either,
and it is what the scripted variant's `--port N` / `-Port N` does: it writes
the nginx port and these two lists into a new `.env`, or moves them in an
existing one:

```ini
CSRF_TRUSTED_ORIGINS=http://localhost:8081,http://127.0.0.1:8081
CORS_ALLOWED_ORIGINS=http://localhost:8081
```

If `docker compose up` stopped on a bind error, free the port and run
`docker compose up -d --force-recreate backend`, with the same `-f` files you
started with: a backend container that failed to publish its port can be left
without a network.

**Local development.** It has two variables of its own and never reads the
Docker ones: `CONFORMITI_DEV_API_PORT` (default 8000) is where `runserver`
listens and where the Vite dev server proxies `/api/` and `/media/`, and
`CONFORMITI_DEV_PORT` (default 5173) is the dev server's own port. Both are
read from the shell, not from `.env`. Set them before running the installer
and it starts both servers on them. When that run creates `.env`, it also adds
the moved web app's origin (`http://localhost:<port>`) to
`CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` in it; a `.env` that was
already there is left alone, and the installer warns instead. Or start the
servers by hand, giving `runserver` the same API port on its command line:

```bash
cd backend && ../.venv/bin/python manage.py runserver 127.0.0.1:8001                 # first terminal
cd frontend && CONFORMITI_DEV_API_PORT=8001 CONFORMITI_DEV_PORT=5174 npm run dev     # second terminal
```

In PowerShell, the same two windows:

```powershell
cd backend; ..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001                          # first window
cd frontend; $env:CONFORMITI_DEV_API_PORT=8001; $env:CONFORMITI_DEV_PORT=5174; npm.cmd run dev    # second window
```

`npm.cmd`, not `npm`: in Windows PowerShell a bare `npm` finds `npm.ps1`,
which the default execution policy refuses (*running scripts is disabled on
this system*). (The end-to-end suite points the proxy at its own backend with
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
including scheme and port. `DJANGO_ALLOWED_HOSTS` takes host names only; the
two origin lists take `scheme://host:port` and matter mostly behind a proxy
(*Moving the ports* explains when). The backend log names the header it
rejected. Behind a proxy, confirm it forwards `Host` and `X-Forwarded-Proto`.
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
