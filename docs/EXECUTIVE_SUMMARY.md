# Conformiti — executive summary

**A self-hosted system of record for a compliance programme.** Controls,
evidence, vendors, risk and access reviews in one place, ending in a sealed
package an assessor can verify without you. MIT licensed, run on your own
infrastructure, with no telemetry, no phone-home and no licence server.

---

## The problem

Most compliance programmes run on a control matrix in a spreadsheet, a folder
of policies nobody has opened since the last audit, and six weeks of heroics
before fieldwork. Three questions expose it every time:

| The question | What usually happens |
|---|---|
| "Where is the evidence for CC6.1?" | Somebody searches a shared drive |
| "When was this policy last reviewed?" | 2023, and nobody noticed |
| "Can the auditor get read access?" | Access that outlives the engagement |

## What it does

- **Three control libraries, seeded on install.** SOC 2 (2017 TSC, rev. 2022),
  ISO/IEC 27001:2022 and PCI DSS v4.0.1: 217 controls, with a crosswalk
  between them and an evidence tree of 1,117 folders generated from them. Your
  own frameworks can be added alongside.
- **Evidence that knows what it proves.** Every document declares the controls
  it satisfies and every control lists its documents, with versions, owners,
  folder-level access and an in-browser viewer.
- **Reviews that chase themselves.** Each document carries a cadence and a next
  review date. Owners are emailed at 30, 14, 7 and 1 days and once when
  overdue, each window sent exactly once.
- **Readiness measured, not asserted.** Implemented divided by applicable,
  scored per control across the signals an auditor asks about, snapshotted
  daily per framework. Nobody types a percentage into this system.
- **Third parties.** A vendor register with assurance on file, a security
  questionnaire the vendor answers by a time-boxed link, and a shared
  responsibility matrix that is typed, prompted or imported.
- **Governance.** A 5x5 risk register, periodic user access reviews whose
  revocations are actually applied, meeting cadences with minutes, and an
  immutable trail of every change and sign-in.

## The audit package

The part that changes how an audit runs. Assemble the controls in scope, seal
the package (every pinned file hashed, the manifest signed with an Ed25519 key
held outside the database), issue it to a named auditor for a fixed window,
and let them verify it offline with a standard-library script that travels in
the bundle. They see exactly what was issued and nothing else. The grant
expires on its own. Next year's package rolls forward from this year's, with a
year-over-year diff.

A signature proves the bundle is unaltered since sealing and that it came from
this installation's key. It does not prove the underlying evidence is true.
That is still the auditor's job, which is the point.

## Why self-hosted matters here

Compliance data is a map of an organisation's weaknesses: which controls are
unimplemented, which reviews lapsed, which vendors were never assessed. The
usual answer is to upload that to a vendor's cloud. Conformiti's answer is
that it never leaves your infrastructure. One `docker compose up` brings up
PostgreSQL, Redis, the API, a worker and nginx with production-safe defaults
and no configuration file required.

One installation can serve several organisations, isolated in the ORM rather
than by remembering to filter, which is what makes it usable by a consultancy
or an MSP.

## State

**Feature complete.** 0.9.5 is the last version number this edition will
carry; releases after it are revision letters on it (0.9.5b, then c, d) and
are maintenance only: security fixes, dependency updates, and compatibility
with new Python, Django and PostgreSQL versions.

It has been through five security reviews, three of them independent,
including a sixteen-lens adversarial review of the multi-tenancy work. Every
finding is closed and each is recorded in the repository with its method and
evidence. The suite is 580 backend tests, 93 end-to-end browser tests run
against both authentication transports, and 19 static checks that run on a
bare interpreter, all on every push across Python 3.11 to 3.14 and PostgreSQL.

## What it deliberately does not do

- **Automated evidence collection** from AWS, GitHub, Okta and the like. That
  is the thing hosted competitors are genuinely good at, it is weeks of work
  per integration, and this edition does not attempt it.
- **Tell you that you are compliant.** It shows what is implemented, what is
  evidenced and what is overdue. The conclusion belongs to your auditor.
- **Meter you.** No seat counting, no usage limits, no call home. The code has
  nowhere to report to.

## Evaluating it

```bash
git clone https://github.com/dboudreau00/Conformiti.git && cd Conformiti
docker compose up -d --build
```

Then `docs` in the repository: [GETTING_STARTED.md](../GETTING_STARTED.md) for
a guided first hour, [SECURITY.md](../SECURITY.md) for the posture and the
residual risks to weigh, [INSTALL.md](../INSTALL.md) for production.

MIT © 2026 elemosecurity. Commercial extensions, content packs and consulting
are offered separately at [conformiti.app](https://conformiti.app); nothing in
this repository is gated behind them.
