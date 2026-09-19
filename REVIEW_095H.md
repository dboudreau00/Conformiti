# Fifth independent review, and what 0.9.5h did about it

A reviewer went through 0.9.5g and opened fourteen findings: no highs, six
medium, eight low. They also re-read the fourteen from 0.9.5f as claims rather
than assuming them, and confirmed all fourteen still hold. That check is worth
as much as the new findings.

Thirteen are fixed here, each with a test that fails on 0.9.5g. One is
deferred, and the reasoning is below rather than in a backlog.

The shape of this set is worth naming, because it is the third review running
to find it: **a rule applied in one place and not in the place beside it.** An
auditor is refused the user list and allowed to name a user through a foreign
key. A capability is checked before the cap that was supposed to limit it. A
CSRF check is added to three endpoints that set a cookie and not to the fourth
that clears one. None of these is a wrong idea; each is a right idea with an
unvisited caller.

Tests: `backend/accounts/tests_review_095h.py`, except where a finding belongs
beside the code it changes: M-2 in `attestations/tests_pbc.py`, L-1 in
`attestations/tests_review_fixes.py`, L-5 in `documents/tests.py`, and L-6 in
`vendors/tests_questionnaire.py`. L-3 is a shell script.

---

## Medium

### M-1: the login minted a refresh token before the second factor

`MFATokenObtainPairSerializer.validate` called the parent first, and
`TokenObtainPairSerializer.validate` authenticates *and* issues. A correct
password with no code therefore left an `OutstandingToken` row holding the raw
refresh JWT, and moved `last_login`, before `MfaChallenge` was raised.
`ATOMIC_REQUESTS` is off, so the raise did not undo it.

The client never saw that token. A database dump, a read replica and the
Django admin did, and unlike the TOTP secret stored in the same dump, which is
encrypted and needs the ring, a signed JWT is usable as it stands. A correct
password alone was enough to plant one.

**Fixed.** The grandparent authenticates without issuing; `_issue()` mints
after the factor has passed. The grandparent is reached through the MRO rather
than imported, so a SimpleJWT that changes the hierarchy fails loudly instead
of quietly minting again. Three tests: the challenge writes nothing, a wrong
code writes nothing, and a completed login still writes exactly one and moves
`last_login`. The third one matters: without it the first two would pass just
as well if minting had broken altogether.

### M-2: an issued auditor could walk the staff directory

`/api/users/` is on the auditor's denied list because it is the staff
directory. `assignee` on a PBC line was a writable foreign key onto every
account in the workspace, and the response carried `assignee_name`. Ids are
sequential. An auditor with a live grant read the directory one request at a
time, and the same walk worked on a PATCH of a line they had raised.

**Fixed.** The field's queryset is empty for an external auditor, so a real id
and an unknown one produce the same 400. A permission check would have
answered 403 for one and 400 for the other, which is the same oracle with
different numbers.

The workflow is unchanged in substance and better in fact: the auditor raises
the request and the organisation routes it, which is how a request list works.
The auditor does not hold the client's staff list, and should not need to.

### M-3: an auditor role could hold capabilities, and they worked

The shipped Auditor role is `is_auditor` alone and is protected. A custom role
was not: `RoleSerializer` stored any combination. `PackageGrant` only asks for
`is_auditor`, so such an account could be issued an engagement, and then:

* `documents.access.effective_access` returns MANAGE on `can_manage_folders`
  before the auditor cap at the foot of the function is reached;
* `accessible_folder_ids` returns every folder on `can_view_all` and never
  caps at all;
* `attestations.access.readable_packages` returns every package on
  `can_manage_frameworks and can_view_all`.

`_CapabilityPermission` refuses auditors on the viewsets, but these read paths
do not go through it. "Give the field auditor view-all so they can see what we
filed" produced an account that could read the whole programme.

**Fixed at the capability, not at the call sites.** `User._cap` returns False
for an external auditor, so every capability read is capped at once and there
is one answer to what a capability means rather than a guard at each caller
that can drift. A superuser is still a superuser: an auditor role on a
superuser is a misconfiguration that account can undo itself. `is_auditor`
remains its own property, so the role still identifies as an auditor; the
`capabilities` payload now reports the capped view, which is what the
interface uses to decide which buttons exist.

**No data migration, deliberately.** Stored flags are left exactly as
configured. Clearing them would rewrite what an operator chose, silently, and
the containment does not need it. The serializer refuses to introduce the
combination from here: creating one, flipping `is_auditor` onto a capable
role, or flipping a capability onto an auditor role. It does *not* refuse an
ordinary save of a row that already holds both, because refusing to let
somebody rename a legacy role would be the silent strip by another route.

The behaviour change is called out in CHANGELOG.md in plain words: an
organisation that used the auditor role to give staff access has to give those
people an ordinary role.

### M-4: the production checklist collapsed every throttle into one bucket

`NUM_PROXIES` defaults to 1, the shipped nginx. INSTALL.md's production
section says to terminate TLS in front of port 8080 and never mentioned it.
After that hop the last address on `X-Forwarded-For` is the terminator, so
login (8/min), anonymous (30/min) and the vendor questionnaire (20/min) all
key on one address for every visitor. An unauthenticated caller who can reach
the hostname, which is the point of putting TLS in front of it, spends the
installation's login budget in a minute and everyone else gets a 429.

**Fixed** in the checklist and in `.env.example`, with the reason rather than
just the number, and the stack warns at boot when `BEHIND_TLS` is on and this
is still 1. A warning and not an error: a terminator that replaces
`X-Forwarded-For` rather than appending to it is a real configuration, and
refusing to start would be wrong.

### M-5: two addresses the outbound guard treated as public

`fec0::/10` is deprecated site-local unicast. Python reports it as
`is_site_local` and `is_global`, and it was in neither the refusal line nor
the supplementary list, so every rule missed it. Listed explicitly rather than
using `ip.is_site_local`, which the standard library deprecates alongside it.

Separately, `assert_safe_url` returned early whenever a proxy applied, before
any address check. A proxy resolves names; it does not change what a literal
is, so `https://169.254.169.254/` left unexamined. A literal is now checked
even under a proxy, while names are still left to the proxy, which is the
documented division.

Jira is the caller that matters: `allowed_hosts=None`, `allowed_ports=None`,
and the base URL is set by anyone who can manage users. Webhooks were never
exposed, because the host must still be Slack or Teams.

### M-6: the server believed the client about https

`SECURE_PROXY_SSL_HEADER` was set whenever `DEBUG` was off. The image pins
`DEBUG` off and `BEHIND_TLS` false, and nginx listens on plain HTTP, so any
client could send `X-Forwarded-Proto: https` and make `request.is_secure()`
true. Cookie flags follow `BEHIND_TLS`, so nothing was stolen; what broke is
origin: `build_absolute_uri` emitted https for the OIDC `redirect_uri` and the
SAML ACS, which are not the addresses those were registered at, and
`passkeys.origins()` reads the same answer.

**Fixed** by gating the setting on `BEHIND_TLS`.

**The reviewer's first suggestion was to default the nginx map to `$scheme`,
and that would have reintroduced 0.9.5f's L-4.** This container listens on 80,
so `$scheme` is always `http`: an outer terminator's `https` would die at
nginx, `BEHIND_TLS=true` would issue Secure cookies for a request Django
thought was plaintext, and `SECURE_SSL_REDIRECT` would redirect to a URL that
arrived the same way. nginx cannot know which hop is trusted. Django can,
because the operator has already said so. The map is unchanged; the trust
decision moved to the one place that has the information. The reviewer agreed
on being shown this.

A terminator that forwards the client's header instead of setting its own will
now loop, which is an operator misconfiguration; INSTALL.md says so at the
step where it matters.

---

## Low

* **L-1.** A sealed package published every live grant, so two audit firms
  issued the same package saw each other's people. A caller who cannot
  assemble packages sees their own row.
* **L-2.** `POST /api/auth/token/clear/` had no CSRF check, because the check
  lives inside cookie authentication and that endpoint exists precisely for
  the case where the access cookie is gone. `SameSite=Lax` covers most of it;
  Chrome's two-minute Lax+POST window does not. The effect was a forced
  sign-out, not a takeover. Now checked, like signing in.
* **L-3.** `scripts/backup.sh` wrote `secrets.tgz` at mode 644 from a
  root container: the signing key, the field-encryption ring and the
  package-signing key. `umask 077`, artefacts 600, directory 700.
* **L-4.** Moving the Jira base URL to another host while leaving the token
  box empty carried the saved credential across and sent it on the next test.
  A host change now clears the token and disables the integration.
  Not pinned to `*.atlassian.net`: self-hosted Jira is real.
* **L-5.** Document writes took the owner short-circuit before anything asked
  whether the caller was an external auditor, so an auditor made the owner of
  a document in a granted folder could edit it. Folder writes were already
  capped.
* **L-6.** A questionnaire link that had expired, been revoked or been
  submitted still returned the vendor's name, the organisation's name, the
  sender, the recipient address and the private message. Draft answers were
  cleared; nothing else was. A link that is not open now says only which state
  it is in, which is what the vendor needs.
* **L-7.** `csv_safe` read the first character of the raw value, so `"\n=cmd"`
  and `" =1+1"` passed. The stripped value decides now. The cell itself is
  unchanged apart from the prefix: an export is evidence, and trimming it
  would alter the record.

---

## L-8, deferred

**A passkey cannot be used as proof when changing a factor.**
`reauthenticated()` accepts a password, an authenticator code or a backup
code. An account provisioned through single sign-on, whose only factor is a
passkey, and whose backup codes are spent, cannot add or remove a factor
without an administrator's reset.

This is not shipped in 0.9.5h, and the reason is that the honest fix is not
small. A passkey is a two-step ceremony: options with stored challenge state,
then an assertion verified against the relying-party id, the origin and the
signature counter, with the clone detector that makes any of it meaningful.
That is the same machinery as signing in. Accepting an assertion in the reauth
body without it would be a new way around the check rather than a fix for it,
and half of a ceremony is worse than none.

It is not a bypass today, and the path out exists:

* enrolling a first passkey issues backup codes, and those satisfy
  `verify_backup_code`, which is the same proof this check already accepts;
* an administrator's MFA reset remains the recovery path for an account with
  nothing left.

A test in `accounts/tests_review_095h.py` holds the first of those, because
the deferral rests on it: if enrolling a passkey ever stopped issuing backup
codes, this would become a lockout rather than an inconvenience.

---

## 0.9.5f, re-checked

The reviewer re-read all fourteen 0.9.5f findings as claims and confirmed each
still holds, including H-3 now that 0.9.5g stops the DEBUG pin from turning
the TLS redirect on with it. Two residuals were re-stated and remain
documented rather than closed: the published-keys route still distinguishes an
organisation that has published a key from one that has not, and SAML replay
is bound by `InResponseTo` and the one-time flow cookie rather than by the
assertion store alone.

## Product decisions, unchanged

The Auditor role reads every access-review snapshot and the whole audit trail
without a live package grant, because an access review is an audit artefact
and the trail is what an auditor is there to read. Folder grants to that role
outlive the engagement. Both were argued in REVIEW_095F.md and are unchanged
here; they are choices, and they are recorded so the next reviewer finds them
argued rather than missed.
