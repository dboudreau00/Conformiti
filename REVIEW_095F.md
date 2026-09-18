# Fourth independent review, and what 0.9.5f did about it

A reviewer went through 0.9.5e against the claims this repository makes about
itself. They opened fourteen findings and named what they had checked and
found sound, which is the more useful half of a review and is reproduced at
the end.

Every finding was real. Every one is fixed, each with a test that fails on
0.9.5e. The reviewer's own summary is worth keeping, because it is accurate:
these are not a collapse of the tenancy model, they are leftover permission
substitutions, an identity-binding hole, an enrolment gap that passkeys had
already closed, and a published image that booted in DEBUG.

The tests live in `backend/accounts/tests_review_095f.py`, except where a
finding belongs beside the check it changes: M-1 in
`accounts/tests_auditor_surface.py`, M-2 in `documents/tests.py`, L-1 in
`accounts/tests_saml.py`, L-2 in `attestations/tests_release_095.py`, and H-3
in `tools/validate.py` and both CI workflows, because it is a property of the
image rather than of the code.

---

## High

### H-1: a hijacked session could enrol its own authenticator

`/auth/mfa/setup/` and `/auth/mfa/verify/` took a live session and nothing
else, while `/auth/webauthn/register/options/` has asked for the password
since 0.9.5. The asymmetry mattered: a stolen access cookie on a
password-only account could enrol the attacker's app, collect the backup
codes the verify step returns, and leave the owner needing the attacker's
phone. The attacker's session stayed valid throughout.

**Fixed.** The helper that passkeys use moved to `accounts/reauth.py` and now
guards setup, verify, disable and backup-code regeneration. First enrolment
on an account with no usable password and no factor is still open, which is
the case an identity provider's account is in and is exactly the exemption
passkeys already make.

### H-2: a self-edited email decided who single sign-on linked to

`ProfileUpdateSerializer` wrote `email` with no verification and no
uniqueness. `OIDC_LINK_BY_EMAIL` defaults to on, and binds an asserted
subject to whichever local account holds that address. Any signed-in caller,
the issued external auditor included, could claim an address belonging to
someone who had not yet signed in through the provider, and take their first
sign-in. Two accounts sharing an address instead produced `ambiguous_email`,
which denies that person SSO.

**Fixed.** Email left the self-service serializer: it is an identity field
that an identity provider matches on, so it is an operator's to set, at
`/users/{id}/`, where the change is recorded. A second account in the same
workspace can no longer take an address that is already in use.

Deliberately scoped to the workspace rather than the installation: a
consultant may hold an account in two organisations on one server under one
address, and the lookup that breaks on a duplicate runs inside a single
workspace.

### H-3: the published image booted with DEBUG on

`DEBUG = env_bool("DJANGO_DEBUG", True)`, and `backend/Dockerfile` set
nothing. Compose sets it, `install.sh` sets it, `install.ps1` sets it, and
the CI image test passed it, so every caller in this repository happened to
set the one variable that had to be set. Publishing the images in 0.9.5e
created the caller that did not: `docker run` came up on `0.0.0.0:8000` with
the browsable API, `SessionAuthentication` on every route, and `MEDIA_ROOT`
served by Django around the X-Accel check.

**Fixed.** `ENV DJANGO_DEBUG=false` in the image. Both CI workflows boot a
container and fail if the banner does not say `DEBUG=off` or if `/api/`
serves the browsable API, and `tools/validate.py` refuses a Dockerfile that
does not pin it.

---

## Medium

### M-1: an issued auditor could read the Jira backlog

`permission_classes` on a DRF `@action` **replaces** the viewset's, so
`@action(..., permission_classes=[IsAuthenticated])` on the issues proxy
dropped `NotExternalAuditor`. Board ids are sequential and the queryset is
workspace-pinned, so trying 1, 2, 3 was the whole attack, and the stored API
token did the fetching. `tests_auditor_surface` classified the collection as
denied and only ever asked the list prefix.

**Fixed.** The action inherits. The suite now walks `get_extra_actions()` on
every registered viewset and resolves each declared permission class against
an auditor; two self-service routes on `users` are named as deliberate
exceptions. The walk found the second one immediately, which is the point of
writing it as a walk.

### M-2: legacy Office was still accepted as evidence

0.9.5b blocked the macro-enabled OOXML extensions and looked inside the
container for a VBA project. None of that reaches `.doc`, `.xls`, `.ppt` or
`.rtf`: an OLE2 compound file is not a zip, and its macros are in a stream.
The macro scan also read only the first two thousand zip entries, so entry
2001 was somewhere to hide.

**Fixed.** The OLE2 signature is refused whatever the file is called, so the
same document renamed to `.dat` is refused too; the legacy extensions are
blocked by name as well, for a clearer message. A packaged OLE object inside
an OOXML file is refused while an embedded worksheet still uploads, and the
scan reads every entry, which costs nothing because the central directory has
already been parsed.

### M-3: the cross-tenant username check was a no-op

The queryset was built outside `unscoped()` and evaluated inside it. A tenant
queryset carries `workspace_id = ActiveWorkspace()`, which resolves when the
query runs, so inside the block the parameter was NULL and nothing matched.
The name then reached `AbstractUser.username`'s global unique constraint and
came back a 500, which is the oracle REVIEW_090 M-1 described, reintroduced by
the fix for it.

**Fixed.** The queryset is built inside the block. Two tests: a name taken in
another workspace is a 400, and the refusal does not say where.

### M-4: a reset left the access token alive

`_blacklist_all` walks `OutstandingToken`, which holds refresh tokens.
Everything else about the session survived until the access token expired, an
hour by default, after the password change, the administrator's reset or the
MFA reset that was meant to end it. The Django admin's own password form did
not call it at all.

**Fixed.** `User.sessions_valid_from` is stamped by `end_all_sessions`, and an
access token issued before that moment is refused. The stamp is floored to the
second because `iat` is whole seconds, which leaves a one-second window in
which a token minted in the same second as the revocation survives; the
alternative refuses the token the person signing in again has just been
handed. `CustomUserAdmin.save_model` now ends sessions and records it.

The first version of this fix stamped inside `_blacklist_all`, which every
caller shared, including signing out. That made signing out of one browser
close the session on the person's other device instantly, which is a product
decision nobody asked for and not what this finding was about. CI found it the
honest way, by holding a second session: the browser suite's stored session
died the moment any test signed out. The two acts are now separate verbs, and
a test holds a second session to keep them that way. Signing out still revokes
every refresh token, as it has since 0.6.1, so no other session can renew
itself.

### M-5: signing in was not CSRF-protected in cookie mode

`_enforce_csrf` lives inside `CookieJWTAuthentication`, so it only ever ran
for a request that already carried a session. `/api/auth/token/`,
`/api/auth/token/refresh/` and `/api/auth/oidc/redeem/` authenticate nobody
and set the cookies, so none of them reached it. `SameSite=Lax` does not
help: the cookie being set is in the response.

**Fixed.** All three check for themselves in cookie mode, and
`/api/auth/config/`, the request the interface already makes before login,
seeds the token. An API client that signs in with cookies must now do the
same, which the changelog and INSTALL.md say plainly.

### M-6: an SSO account could not remove a factor

Passkey removal and MFA disable called `check_password`, which is always
false for an account with no usable password. The owner of a passkey the
server had flagged as possibly cloned could not take it off; the only way out
was an administrator's reset, which removes every factor and every session.

**Fixed.** Both use the same proof as enrolment, which accepts a backup code.

### M-7: a build could bake a developer's keys into the image

`backend/.dockerignore` excluded the local database and the virtualenv, not
`.field-encryption-key` or `.package-signing-key`, which the local installer
leaves in that directory. Harmless while nobody published the image; 0.9.5e
publishes it.

**Fixed.** Both, plus `*.pem` and `*.key`, and the validator fails the build
if they are ever dropped from that file.

---

## Low

### L-1: a SAML bearer confirmation with no expiry

The profile requires `NotOnOrAfter` on `SubjectConfirmationData`. 0.9.5b made
`Destination` and `Recipient` required and left this one honoured when
present, so an assertion that omitted it was bounded by the `Conditions`
window, or by an hour when that was absent too. After the replay row is
pruned, the same assertion posts again. **Fixed:** required, like the other
two.

### L-2: the published-keys route still distinguished slugs

Two leaks. "Several organisations" counted only active workspaces, so an
installation with one active and any number of archived ones took the
single-tenant path, where the answer was `SigningKey.objects.all()` unscoped:
every organisation's slug, including the ones that had left. And an unknown
slug answered 400 while a known one answered 200.

**Fixed.** The single-tenant path resolves to that workspace and filters by
it. An unknown slug answers exactly as an organisation that exists and has
never signed anything.

This narrows the oracle rather than closing it: an organisation that has
published a key still answers differently from one that has not, which is
what publishing a key means. Closing it entirely would mean authenticating
the endpoint, and an auditor could then not verify a bundle without an
account on the server it came from, which is the property the scheme exists
for.

### L-3: the boot banner contradicted the boot

Its own defaults read `DJANGO_DEBUG` and `SEED_DEMO_DATA` as on while the
code it described defaulted them off, so a bare `docker run` announced demo
accounts and a published password that were never seeded. **Fixed:** the
defaults match what the image does.

### L-4: nginx overwrote the scheme

`proxy_set_header X-Forwarded-Proto $scheme` inside a container that listens
on 80 is always `http`, so an outer TLS terminator's `https` was discarded.
`BEHIND_TLS=true` then issued Secure cookies for a request Django thought was
insecure, and `SECURE_SSL_REDIRECT` could redirect to a URL that arrived back
the same way. **Fixed:** the client's header wins, `$scheme` is the fallback.

### Also raised, also fixed

* `.env` is written mode 600 by the POSIX installer. The PowerShell one says
  what it cannot do rather than pretending to set an ACL.
* `ip_is_public` unwraps an IPv4-mapped address, so `::ffff:100.64.0.1` is
  checked as the carrier-grade NAT address it is.
* The OpenID Connect client goes through `config.outbound`, like every other
  server-side request since 0.9.5b. The issuer is the operator's setting; the
  token and userinfo endpoints come out of the provider's discovery document.

---

## Not opened, and why

The reviewer listed what they checked and found in the shape the
documentation claims. That list is reproduced here because it is evidence
about the parts nobody had to change: the ORM tenancy pin and its IDOR tests,
the cookie prefixes and the refresh path, webhook secrecy and the outbound
pin, the auditor's deny-by-default list, SAML signature wrapping and replay,
OIDC PKCE and the refusal to auto-link privileged accounts, TOTP counter
spending and single-use backup codes, the fail-closed passkey clone detector,
the preview pipeline's bounds, and the X-Accel path.

## One product decision, left as a decision

The Auditor role can read every access-review snapshot and the whole audit
trail (emails, last sign-ins, capabilities, client addresses) without a
live package grant, because an access review is an audit artefact and the
trail is what an auditor is there to read. It is also how a firm invited onto
one engagement reads the staff directory. Folder grants to that role outlive
the engagement in the same way.

That is a choice rather than an oversight, and it is not changed here. It is
recorded so the next reviewer finds it argued rather than missed.
