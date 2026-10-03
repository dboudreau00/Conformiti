# Conformiti executive summary

**A self-hosted system of record for a compliance programme.** Controls,
evidence, vendors, risk and access reviews in one place, ending in a sealed
package an assessor can verify without you. MIT licensed, run on your own
infrastructure, with no telemetry, no phone-home and no licence server.

---

## The problem

Most compliance programmes run on a control matrix in a spreadsheet, a folder
of policies nobody has opened since the last audit, and six weeks of scrambling
before fieldwork. Three questions show the gaps:

| The question | What usually happens |
|---|---|
| "Where is the evidence for CC6.1?" | Somebody searches a shared drive |
| "When was this policy last reviewed?" | Nobody can say without opening the file |
| "Can the auditor get read access?" | Access that outlives the engagement |

## What it does

- **Three control libraries, seeded on install.** SOC 2 (2017 TSC, rev. 2022),
  ISO/IEC 27001:2022 and PCI DSS v4.0.1: 217 controls, with a crosswalk
  between them and an evidence tree generated from them (249 folders in the
  app, one per framework, category and control; 1,117 on disk, where each
  control also gets policies, procedures, evidence and forms folders). Your
  own frameworks can be added alongside.
- **Evidence mapped to controls.** Every document declares the controls
  it satisfies and every control lists its documents, with versions, owners,
  folder-level access and an in-browser viewer.
- **Automatic review reminders.** Each document carries a cadence and a next
  review date. Owners, and the organisation's compliance mailbox, are emailed
  as a review falls due (30, 14, 7 and 1 days by default) and once when it is
  overdue: at most one email per document a day, for the nearest window it has
  entered, never repeated for a window already sent, and retried the next day
  if the send fails.
- **Calculated readiness.** Implemented divided by applicable,
  scored per control across the signals an auditor asks about, snapshotted
  daily for the whole programme and broken down live per framework. No
  percentage is entered by hand.
- **Third parties.** A vendor register with assurance on file, a security
  questionnaire the vendor answers by a time-boxed link, and a shared
  responsibility matrix that is typed, prompted or imported.
- **Governance.** A 5x5 risk register, periodic user access reviews whose
  revocations are applied, meeting cadences with minutes, and a
  read-only trail of every change and sign-in.

## The audit package

The part that changes how an audit runs. Assemble the controls in scope, seal
the package (every pinned file hashed, the manifest signed with an Ed25519 key
held outside the database), issue it to a named auditor for a fixed window,
and let them verify it offline with a standard-library script that travels in
the bundle. Through the grant they read exactly the evidence that was issued,
and the grant expires on its own. The Auditor role can also read the
organisation's audit trail and its access reviews, and any folder you grant it
separately, for as long as the account is active, whether or not a grant is
live; [REVIEWS.md](../REVIEWS.md) records that decision. Next year's package
rolls forward from this year's, with a year-over-year diff.

A signature proves the bundle is unaltered since sealing and that it came from
this installation's key. It does not prove the underlying evidence is true.
That remains the auditor's job.

## Why self-hosted matters here

Compliance data is a map of an organisation's weaknesses: which controls are
unimplemented, which reviews lapsed, which vendors were never assessed. Hosted
tools upload that to a vendor's cloud. Conformiti keeps it on your
infrastructure. Nothing leaves it unless you connect something, and each connection
(email, Slack or Teams, Jira, single sign-on) is opt-in. Some carry names: a reminder email's subject holds the document's
name.

One `docker compose up` brings up PostgreSQL, Redis, the API, a worker and its
scheduler, and nginx, with no configuration file required and safe defaults:
DEBUG off, a secret key generated on first boot, and nothing but nginx
published to the network. It serves plain HTTP and prints email to its log
until you configure them; [INSTALL.md](../INSTALL.md) lists what production
adds, including TLS in front.

One installation can serve several organisations, isolated in the ORM rather
than by remembering to filter, which is what makes it usable by a consultancy
or an MSP.

## State

**Feature complete.** 0.9.5 is the last version number this edition will
carry; releases after it are revision letters on it (0.9.5b, then c, d) and
are maintenance only: security fixes, dependency updates, and compatibility
with new Python, Django and PostgreSQL versions.

It has been through repeated security reviews, most of them independent,
including an adversarial review of 0.9.0, the release that introduced
multi-tenancy, by sixteen reviewers. Each is recorded in the repository with
its method and evidence, and every finding is fixed or written down as
deliberately left alone. Every push to main and every pull request runs the
backend test suite across Python 3.11 to 3.14 and PostgreSQL, an end-to-end
browser suite against both authentication transports, and a static validator
that needs nothing but a bare interpreter.

## What it deliberately does not do

- **Automated evidence collection** from AWS, GitHub, Okta and the like. That
  is the thing hosted competitors are good at, it is weeks of work
  per integration, and this edition does not attempt it.
- **Tell you that you are compliant.** It shows what is implemented, what is
  evidenced and what is overdue. The conclusion belongs to your auditor.
- **Meter you.** No seat counting, no usage limits, no call home. The code has
  nowhere to report to.

## Evaluating it

```bash
git clone https://github.com/dboudreau00/Conformiti.git && cd Conformiti
git checkout "$(git tag --list 'v*' --sort=-v:refname | head -n1)"   # the newest release
docker compose up -d --build
```

Then read [GETTING_STARTED.md](../GETTING_STARTED.md) for
a guided first hour, [SECURITY.md](../SECURITY.md) for the posture and the
residual risks to weigh, [INSTALL.md](../INSTALL.md) for production.

MIT © 2026 elemosecurity. See [conformiti.app](https://conformiti.app) for
what is offered around it; nothing in this repository is gated behind it.
