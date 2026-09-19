# Sixth independent review, and what 0.9.5i did about it

Three findings, no highs, and two of them are defects in fixes 0.9.5h shipped
the same day. That is the useful part of this review: it re-read the fixes
rather than the code they replaced.

The shape is the one that has now run through four consecutive reviews: **a
rule applied to one caller and not to the one beside it.** 0.9.5h stopped an
auditor naming a person on the write path and left the filter on the same
collection open. 0.9.5h set a file mode that could not take. Both are smaller
than what came before them, and both are the same family.

All three are fixed here with a test apiece. The read of what was left
deliberately open is at the end, unchanged.

---

## L-1: the assignee oracle was closed on write and left open on the filter

`filterset_fields` on the request list included `assignee`, and django-filter
generates a `ModelChoiceFilter` for a foreign key. A ModelChoiceFilter
validates membership: an id that belongs to an account answers 200, an id that
belongs to nobody answers 400. An external auditor may GET that collection
with the grant they already hold to raise a line, and ids are sequential.

It is narrower than the disclosure M-2 closed in 0.9.5h, because these routes
return no names: it answers whether an id is a person, not who. The same shape
was on `/api/documents/?owner=` and `/api/audit-log/?user=`, and the trail is
readable by an issued auditor with no live grant at all, by the product
decision recorded in REVIEW_095F.md.

**Fixed** by filtering on the number instead, in `config/personfilters.py`. An
id nobody holds now filters to nothing and answers 200 with an empty page,
which is exactly what a real person with no rows answers, so the reply carries
no information about who exists. Filtering by a real id still narrows the
result, and a test asserts that, because closing an oracle by breaking a
feature would not be a fix.

**And a walk, so the next one cannot arrive quietly.** 0.9.5h wrote a walk
over `@action` routes for this same reason and it found a second instance
immediately. `accounts/tests_review_095i.py` now resolves the filterset DRF
would build for every collection on the auditor's allowed list and refuses any
filter on a person that validates membership. Reintroducing the audit-trail
filter makes it fail by name, which is how it was checked rather than assumed.

## L-2: the mode 0.9.5h set could not take

`scripts/backup.sh` created its archives with a container, then chmodded them
from the host:

```sh
docker run ... alpine:3.20 tar czf "/out/$v.tgz" -C /src .
chmod 600 "$out"/*.tgz ... 2>/dev/null || true
```

The tar runs as root inside the container, so on Linux the archive lands
`root:root 644`. The chmod then runs as the operator, who is in the docker
group and is not root, and fails. `|| true` swallowed the failure, and the
script printed `written to $out (mode 600, ...)`. That is worse than not
having written it: it is a reassurance the script had not earned.

Verified rather than reasoned about. As the invoking user on a Linux host:

```
as created:   old.tgz 644 root      new.tgz 600 root
host chmod as a non-root operator:
  chmod: changing permissions of 'old.tgz': Operation not permitted
  after: old.tgz 644 root
```

What actually closed L-3 in 0.9.5h was the destination directory being 700.
That holds for the default destination and stops holding the moment anyone
copies `secrets.tgz` somewhere else or points the script at a directory that
already exists.

**Fixed** by setting the mode inside the container that creates the file:
`sh -c "umask 077 && tar czf /out/$v.tgz -C /src . && chmod 600 /out/$v.tgz"`.
The directory chmod no longer hides its own failure. `tools/validate.py`
refuses a backup script that chmods behind `|| true`, or that does not set the
mode in the container, because the failure mode here is one that conceals
itself.

## L-3: the sentence was wider than the code

`public_state` for a link that is not open returned `{status, questions,
answers, expires_at, submitted_at}`. CHANGELOG said such a link "says only
that". `submitted_at` on a stolen URL is when the vendor filed.

It is small beside the names 0.9.5h removed, and the fix is to make the code
match the claim rather than narrow the claim: a dead link returns its state,
an empty question list and an empty answer set. The page needs the state to
say "this link has expired" and needs nothing else to say it.

---

## Confirmed, not reopened

The reviewer re-checked the 0.9.5h fixes and the older residuals. Recorded
here so the next pass does not re-derive them:

* The tenancy pin and the IDOR suite; cookie CSRF on login, refresh, redeem
  and now clear; `sessions_valid_from` still floored to the second; OLE2 by
  signature; the auditor `@action` walk; the outbound pin and its refusal to
  follow redirects; Jira issues inheriting the viewset's permissions; X-Accel
  still internal; backup codes still spent in the database; SAML
  `NotOnOrAfter` still required.
* The Django admin still registers `Role` without a `clean()`, so the
  auditor/capability combination can still be stored there. `_cap` means
  storing it grants nothing, and a test in `tests_review_095i.py` now holds
  that, so the admin gap is contained rather than merely unnoticed.
* `2002::/16` and `2001:0::/32` still read as public. 6to4 and Teredo are not
  the range `fec0::/10` was, and the caller is an operator typing a Jira base
  URL. Not added.
* `/api/health/` still creates the signing key on first call. Workers no
  longer reach it and the fingerprint is already published.
* The published-keys route still distinguishes an organisation that has
  published a key. Authenticating it would break offline verification, which
  is the property the scheme exists for.
* Access reviews and the audit trail are readable by an issued auditor with no
  live grant, and folder grants outlive the engagement. Both are product
  decisions, argued in REVIEW_095F.md.

## Still deferred

**L-8 from the fifth review: a passkey as proof when changing a factor.**
Unchanged, and for the same reason: the honest fix is a two-step ceremony with
stored challenge state, origin and clone detection, and half of one would be a
new way around the check rather than a fix for it. The reviewer agrees it
should wait until the ceremony is real. Enrolling a first passkey issues
backup codes, which the check already accepts, and an administrator's MFA
reset remains the recovery path. REVIEW_095H.md carries the argument.
