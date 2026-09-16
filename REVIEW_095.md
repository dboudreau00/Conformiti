# Conformiti 0.9.5 — third-party review, closed in 0.9.5b

**Date:** 2026-09-12, fixed 2026-09-15 · **Reviewed tree:** v0.9.5 (local
`a96ff49`, publish `85e5f00`) · **Method:** an independent source review was
received; every finding below was then checked against the tree before being
accepted. No finding is listed on the reviewer's word alone.

**Result.** 9 findings received, **9 verified**, 0 rejected. One (S-7) is real
but reaches less far than the report claims, and is re-scored here. **All nine
are fixed in 0.9.5b**, each with a test that fails against 0.9.5.

Two things were found while fixing rather than by the review, and are recorded
at the end: a key-rotation gap that would have made the newly encrypted
columns unreadable, and a range of addresses the standard library does not
call private.

0.9.5 was the last public *feature* release. Security maintenance continues, so
these land as **0.9.5b**.

## Where each fix lives

| ID | Fixed in | Tested by |
|---|---|---|
| S-1 | `accounts/workspace_views.py`, `pages/Account.jsx` | `accounts/tests_review_095.py`, `tests_auditor_surface.py`, `e2e/tests/settings.spec.js` |
| S-2 | `config/outbound.py` (new), `notifications/webhooks.py`, `accounts/models.py` | `config/tests_outbound.py`, `accounts/tests_review_095.py` |
| S-3 | `accounts/models.py`, `accounts/migrations/0011_encrypt_webhooks.py` | `accounts/tests_review_095.py` |
| S-4 | `documents/uploads.py` | `documents/tests.py` |
| S-5 | `vendors/questionnaire.py` | `accounts/tests_review_095.py`, `vendors/tests_questionnaire.py` |
| S-6 | `accounts/saml.py`, `config/settings.py` | `accounts/tests_saml.py` |
| S-7 | `config/urls.py`, `api/client.js` | `accounts/tests_review_095.py` |
| S-8 | `attestations/views.py` | `attestations/tests_review_fixes.py` |
| S-9 | `docker-compose.yml`, `entrypoint.sh`, `install.sh`, `install.ps1` | `.github/workflows/ci.yml` (compose job) |

## What was found

| ID | Sev | Finding | Verified at |
|---|---|---|---|
| S-1 | High | Slack/Teams webhook URLs are returned to every signed-in member, the external auditor included | `accounts/workspace_views.py:44`, `:75`, `accounts/tests_auditor_surface.py:38` |
| S-2 | Medium | Slack host check is a substring test, Teams has none, the dispatcher follows redirects and never checks the address | `accounts/workspace_views.py:31`, `notifications/webhooks.py:158` |
| S-3 | Medium | Webhook URLs are stored in plaintext while comparable secrets are encrypted; the admin skips the serializer | `accounts/models.py:30`, `accounts/admin.py:77` |
| S-4 | Medium | Macro-enabled Office documents are accepted as evidence | `documents/uploads.py:16` |
| S-5 | Medium | Mailed questionnaire links fall back to the request `Origin` | `vendors/questionnaire.py:64` |
| S-6 | Low–Med | SAML `Destination` and `Recipient` are accepted when absent | `accounts/saml.py:306`, `:336` |
| S-7 | Low | Sign-out cannot see the refresh cookie, so the 7-day token survives | `accounts/session_views.py:68`, `accounts/cookie_auth.py:94` |
| S-8 | Low | The signing-key directory distinguishes a real workspace slug from a wrong one | `attestations/views.py:417` |
| S-9 | Info | The demo dataset is still seeded by default and advertised on the health endpoint | `docker-compose.yml:68`, `config/health.py:82` |

---

## S-1 — webhook URLs readable by every role

**Confirmed, and the reviewer's read of the permission is exactly right.**
`WorkspaceViewSet` sets `permission_classes = [IsSuperuserOrReadOwn]`, which
subclasses `IsAuthenticated` only. That *replaces* the project default pair, so
`NotExternalAuditor` never runs here, and `IsSuperuserOrReadOwn` returns `True`
for `list`, `retrieve` and `current` to anyone signed in. The auditor-surface
suite confirms the intent: `workspaces` is on its allow-list, "their own, to
name it on screen". An issued external auditor, a Viewer and a Control Owner
can all read `slack_webhook_url` off `GET /api/workspaces/current/`.

`GET /api/notifications/channels/` already returns booleans and never a URL.
The workspace serializer is the inconsistency.

**Fixed.**

1. Both URL fields are `write_only=True` on `WorkspaceSerializer`. A webhook
   URL is never echoed after it is saved, to anyone, superuser included.
2. Read-only `slack_configured` / `teams_configured` booleans take their place,
   matching the shape `/api/notifications/channels/` already used.
3. `to_representation` trims the payload by role: a non-superuser reader gets
   `id`, `name`, `slug`, `is_active`, `created_at` and nothing else.
   `notification_email` and the user count are the organisation's business, not
   its external auditor's.

**The SPA was the part that could bite.** `Account.jsx` seeded the form from
the response and always PATCHed all three fields. The moment the URLs stopped
coming back, the next save of the reminder mailbox would have posted two empty
strings and silently deleted both configured channels. So the boxes now start
empty and say whether a channel is configured, a webhook field is sent only
when someone typed into it, and a separate Remove control is the one path that
sends `""`.

**Tested** at three levels, because the defect spanned them: the API never
echoes a URL to any of the five roles (`tests_review_095.py`); the
auditor-surface suite asserts the same for the route it deliberately allows,
which is where this should have been caught in 0.9.5; and an end-to-end test
saves a webhook, saves the mailbox again, and proves the channel survived.

## S-2 — substring allow-list, and an SSRF that follows redirects

**Confirmed.** `_https_or_blank` does `expected_host not in value.lower()`, so
`https://hooks.slack.com.attacker.tld/x` and `https://attacker.tld/?hooks.slack.com`
both pass. Teams gets no host check at all. At send time `webhooks._post` only
re-checks the `https://` prefix and hands the URL to `urllib.request.urlopen`,
which follows redirects and resolves whatever it is given — so a 302 to
`http://169.254.169.254/` or `http://redis:6379/` is reached from inside the
container network. Writes are superuser-only through the API, but
`WorkspaceAdmin` (`accounts/admin.py:77`) has no `clean()`, and the model has
none either, so the admin stores anything.

The product already contains the correct pattern, in `integrations/jira.py`:
`_NoRedirect`, `_PinnedHTTPSConnection`, `_PinnedHTTPSHandler`, `_ip_is_public`,
`_assert_safe_base_url`. There should be one copy of it.

**Fixed.**

1. New `backend/config/outbound.py` holds the four Jira helpers, unchanged in
   behaviour, raising a module-level `OutboundError` that carries a `code` so
   each caller can phrase its own message. `check_shape` judges the URL text:
   https, a hostname, **no userinfo**, port 443, and a host matched label by
   label. `assert_safe_url` adds resolution and returns the address to pin to.
   The split exists so a form can reject a wrong URL without depending on DNS,
   while nothing is ever *sent* without the resolution step.
2. `integrations/jira.py` imports from it and translates each code back into
   the message it always used, so its behaviour and its tests are unchanged.
3. Host lists, settings-driven so an operator on a different tenant host is not
   stuck: `WEBHOOK_ALLOWED_HOSTS_SLACK` defaults to `hooks.slack.com`;
   `WEBHOOK_ALLOWED_HOSTS_TEAMS` defaults to `webhook.office.com`,
   `outlook.office.com`, `outlook.office365.com`, `logic.azure.com` — the legacy
   Office 365 connector hosts plus Power Automate Workflows, which is where
   Microsoft has moved Teams incoming webhooks.
4. Enforced at **both** ends. `accounts.models.validate_webhook_url` replaces
   `_https_or_blank` as the typing-time check, so the operator gets a 400;
   `webhooks._post` runs the full check before every POST and records
   `refused: …` in `WebhookDelivery`, because a stored value may predate this
   rule or have arrived through the admin, a fixture or a restored backup.
5. `_post` dials through the no-redirect, pinned-address opener rather than
   bare `urlopen`.

**Tested.** `config/tests_outbound.py` covers the module directly, so a change
to it cannot be judged only by whether its two callers still pass:
label matching, the addresses that are not public, every refusal code, the
pinned address, and a host that passes the allow-list but resolves inside the
network. `accounts/tests_review_095.py` covers it through the product: six
spellings of someone else's host refused at the API, a stored URL refused
before a post, and a redirect recorded rather than followed.

The webhook tests no longer patch `urllib.request.urlopen`, because posting no
longer goes through it. They replace `webhooks._open`, a named seam, and stub
DNS to one public address, so the suite reaches the network no more than it
did before while every other check runs for real.

## S-3 — webhook URLs not encrypted at rest

**Confirmed.** `config/fieldcrypto.EncryptedCharField` exists for precisely this
case, secrets the server must read back, and is used for the TOTP secret
(`aad_from="user_id"`) and the Jira token (`aad_from="id"`). The two webhook
columns are plain `URLField`s.

**Fixed.** `EncryptedCharField(max_length=800, blank=True, aad_from="id")` for
both. The length matters: the envelope is base64 over ciphertext plus tag plus
the `fc1$<key-id>$<nonce>$` header, so a 500-character URL does not fit in 500.
Keep a 500-character ceiling in serializer validation so the operator-facing
limit is unchanged. Migration `accounts/migrations/0011_encrypt_webhooks.py`
(0010 is the last): alter the columns, then re-save existing rows through the
field so stored plaintext becomes ciphertext, following
`0002_encrypt_secrets_at_rest.py`. The read path already accepts plaintext, so a
half-migrated or key-less database degrades to read-only rather than losing data.

Add `Workspace.clean()` calling the same validator, which closes the admin
bypass — Django's ModelForm runs `full_clean`, so no admin change is needed
beyond the model.

## S-4 — macro-enabled Office accepted

**Confirmed.** `.html`, `.htm`, `.svg` and `.js` are blocked; `.docm`, `.dotm`,
`.xlsm`, `.xltm`, `.xlam`, `.xlsb`, `.pptm`, `.potm`, `.ppsm` and `.sldm` are
not. Scanning is off by default (`CLAMAV_ENABLED: ${CONFORMITI_SCANNING:-false}`).

**Fixed.** Added the macro-enabled set plus `.mht`, `.mhtml` and `.xhtml` to
`BLOCKED_EXTENSIONS`, and sniff the container rather than trusting the name: an
uploaded OOXML file is a zip, so open it and refuse it if it holds
`vbaProject.bin` or any `.bin` macro part — that catches a `.docm` renamed to
`.docx`, which is the actual evasion. Error text stays in the existing voice:
export to PDF and upload that.

**Not doing: scanning on by default.** The `clamav` service is in compose and
the reviewer is right that fail-closed scanning is strictly better, but turning
it on by default makes a first `docker compose up` pull a container and a
virus-definition database before anything works, and makes every upload 503
until `freshclam` finishes. That is a worse first run for every operator, to
mitigate a class of file we are now refusing outright. The compose file states
that trade-off plainly instead, and says to turn scanning on for any
installation holding evidence you did not create.

## S-5 — mailed link base trusts `Origin`

**Confirmed.** `PUBLIC_URL` defaults to empty (`config/settings.py:718`) and is
commented out in `.env.example`, so the shipped default takes the `Origin`
branch. The questionnaire token is a bearer credential, so a spoofed `Origin` on
the send call puts an attacker's host in the vendor's email.

**Fixed by failing closed.** Off DEBUG, `public_base` raises rather than
falling back, and the send is refused with a message naming `PUBLIC_URL`. In
DEBUG the fallback survives, because a developer moves between localhost ports
all day, but only to an `Origin` the operator already named in
`CSRF_TRUSTED_ORIGINS` or `CORS_ALLOWED_ORIGINS`.

Two departures from the plan. The refusal is a `QuestionnaireError`, giving a
400 with a field name, rather than a new 409: that is the shape the send
endpoint already uses and the SPA already renders. And the check runs *before*
the transaction, so a refused send does not first revoke the vendor's live
invitation to make room for a link that cannot be built. No boot-time check
was added: an installation upgrading from 0.9.5 has no `PUBLIC_URL` by
definition, and refusing to start would turn a questionnaire problem into an
outage.

## S-6 — SAML `Destination` and `Recipient` optional

**Confirmed, both of them.** `if destination and destination != flow["acs"]`
accepts a response with no `Destination`; the `SubjectConfirmationData` loop
treats a missing `Recipient` as confirmation. HTTP-POST binding requires
`Destination`, and `flow["acs"]` itself comes from `request.build_absolute_uri`
unless `SAML_ACS_URL` is pinned, leaving `ALLOWED_HOSTS` as the only backstop.

**Fixed.** Both are required on the POST binding now: absent is a hard fail.
The test harness in `tests_saml.py` gained a way to drop one attribute without
the other, so each is proved separately.

On pinning the ACS: making `SAML_ACS_URL` and `OIDC_REDIRECT_URI` mandatory
would break every working SSO installation on upgrade, to close a gap that
`ALLOWED_HOSTS` already closes. Django refuses a request whose `Host` is not
listed, and the shipped default lists two names. So the guard is narrowed to
the case where that backstop is genuinely absent: single sign-on enabled, off
DEBUG, with `DJANGO_ALLOWED_HOSTS=*`, now refuses to start unless both URLs
are pinned.

## S-7 — sign-out cannot see the refresh cookie

**Confirmed, and re-scored down slightly.** The refresh cookie's path is
`/api/auth/token/` (`cookie_auth.py:94`), so `POST /api/auth/session/clear/`
does not receive it. `SessionClearView` also accepts `refresh` in the body, but
the cookie is `HttpOnly`, so the SPA cannot supply it. With a *live* access
cookie `_blacklist_all` revokes everything, which is the common path; only the
expired-access-cookie case — the case the endpoint was written for — leaves the
outstanding refresh token valid until it expires naturally.

**Fixed.** The same view is mounted a second time at `POST /api/auth/token/clear/`,
inside the refresh cookie's path, so the browser attaches the cookie. The SPA
calls that one and falls back to `/api/auth/session/clear/` on a 404 so an older
build keeps working. `/api/auth/session/clear/` stays, unchanged, because
`LogoutView` and existing clients depend on it.

**Tested** with no access cookie at all, which is the case that was broken: the
refresh cookie alone reaches the token-path endpoint and its `OutstandingToken`
comes back blacklisted. The 0.9.5 suite proved only that the cookies were
cleared, which was never the part in doubt.

## S-8 — signing-key directory is a slug oracle

**Confirmed.** An unknown slug 404s while a real one returns 200, unauthenticated.

**Fixed.** An unknown slug now gets the same 400, with the same body, as a
request that names no organisation on a multi-workspace installation, so
presence is indistinguishable. The test that asserted the 404 asserts the
pair are identical instead.

## S-9 — demo dataset on by default

**Confirmed.** `SEED_DEMO_DATA: ${SEED_DEMO_DATA:-true}` in compose, and
`/api/health/` reports `demo_accounts` to anyone.

**Fixed by defaulting the seed off**, in `docker-compose.yml`, in
`backend/entrypoint.sh`, and in both installers, which write `SEED_DEMO_DATA`
into `.env` and would otherwise have overridden the compose default. The
scripted flag is now `--demo` / `-Demo`; `--no-demo` still works and now
agrees with the default. The CI compose job asks for the dataset explicitly,
because it signs in as a demo account.

**`demo_accounts` deliberately stays on the unauthenticated health payload**,
which is a departure from the plan. Hiding it reads well until you follow it
through: that field is what puts "this installation still has its seeded demo
accounts, remove them before real use" on the **sign-in page**, which is the
one screen the person who can act on it is looking at. Gating it would have
removed the warning and left the accounts. What it discloses is five usernames
whose password is random and printed once; an installation that still has them
has a larger problem, and is now being told so. With the seed off by default,
a deployment has nothing to disclose unless its operator asked for the tour.

---

## Two things the review did not find

**The key-rotation command would have made the new columns unreadable.**
`manage.py rotate_field_keys` carried a hand-written list of encrypted
columns, under a comment asking the next person to extend it. S-3 encrypts two
more, and rotating keys without extending that list would have left those rows
on the old key. Step 3 of a documented rotation is "drop the old key", so the
next rotation after upgrading would have silently destroyed every stored
webhook. The command now asks the model registry instead of a list, which
cannot go stale, and a test asserts all four encrypted columns are found. The
warning comment was accurate and still insufficient: the fix is to remove the
thing that needs remembering.

**Carrier-grade NAT is not "private" to Python.** The first version of
`ip_is_public` leaned on `ipaddress.is_private` and a comment claiming it
covered RFC 6598. It does not: `100.64.0.1` is a public address as far as the
standard library is concerned, and several hosting providers address tenant
networks out of that range. The module now refuses it explicitly, along with
RFC 6890 protocol assignments, RFC 2544 benchmarking space and the NAT64
prefix. Found by a unit test written against the claim in the comment.

## What was run

| Gate | Result |
|---|---|
| Backend suite | 574 tests, OK, 1 skipped |
| `makemigrations --check` | no changes detected |
| Static validator | 19 checks pass, 0 errors, 0 warnings |
| Frontend build | clean |
| End-to-end, header transport | 93 passed |
| End-to-end, cookie transport | 92 passed, 1 skipped |

The `compose` CI job also exercises this release's ingest change end to end,
because it uploads, downloads through X-Accel, backs up and restores.

`REVIEW_090.md` stays as the record of the earlier 50-finding pass; this
document does not replace it.

## Pro overlay impact

The overlay patches `App.jsx`, `nav.js` and `NavIcon.jsx` only, none of which
these fixes touch, so no patch conflict. Two things do need checking after the
core lands:

1. Re-run the overlay's `core` gate, which runs the public suite under Pro
   settings — the S-1 serializer change and the new `accounts` migration are what
   it would catch.
2. Audit the Pro surfaces for the same two patterns: any serializer echoing a
   stored credential (API key management, connectors, white-label), and any
   outbound POST not going through the new `config/outbound.py`.
