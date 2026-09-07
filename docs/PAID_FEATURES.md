# Paid features — scaffold and plan

Working notes for the commercial tier. Nothing here is built. Each entry says
what it is, where it lands in the existing code, what it costs to build, and
what has to be decided before anyone writes a line. Prices are deliberately
absent; they are a separate conversation.

---

## 0. The licensing problem, first

Conformiti is MIT. MIT lets anyone take a paid module, delete the licence
check and redistribute it. So the tier has to be structured before it is
built, and the choice changes the architecture of everything below.

| Model | How it works | Cost |
|---|---|---|
| **Open core** (recommended) | The MIT repo stays exactly as it is. Paid features live in a **separate private repo** under a commercial licence, installed as a Django app (`INSTALLED_APPS += ["conformiti_pro"]`) and a set of SPA routes. The core exposes stable extension points; the module registers against them. | A plugin seam in the core, and the discipline to keep it stable. |
| **Hosted only** | The paid features exist only on infrastructure you run. Nothing to leak. | You are now a SaaS operator: uptime, backups, breach exposure, and the customer's data on your disk. Several features below are *worse* hosted (see §5). |
| **Relicense new modules** (BSL / Elastic 2.0) | New directories carry a source-available licence with a time bomb to MIT. | Community friction, and it does not apply retroactively to what is already MIT. |

**Recommendation: open core.** It keeps the trust story that sells this
product ("no telemetry, no licence server, run it yourself") while giving the
paid module a licence that means something.

**Prerequisite work (do this first, ~1 week):**

- An entry-point registry in the core: `conformiti.plugins` with hooks for
  extra installed apps, extra API routers, extra SPA nav entries, extra
  settings, and extra seed data. Today the SPA's nav is a static list in
  `frontend/src/nav.js` and the routers are hard-wired in each `urls.py`.
- A licence-key check that is **honest**: it gates support and updates, not
  runtime. A key that phones home contradicts the README's "no telemetry, no
  phone-home, no licence server" promise, which is a selling point. Verify an
  offline signed licence file (you already ship Ed25519 signing and a
  stdlib verifier — reuse `attestations/signing.py`).

---

## 1. Compliance packages — HIPAA, SOC 2 Type II, ISO 42001, ISO 27017, NIST 800-53

**What it is.** More control libraries, sold as packs.

**Where it lands.** This is the *cheapest* feature on the list and the one
most ready to build. The machinery already exists and is generic:
`backend/compliance/data/*.json` + `seed_frameworks --workspace <slug>` +
the crosswalk. A pack is a JSON file and a crosswalk entry. `Framework.key`
is already unique per workspace (0.9.0), so packs install per customer.

**Effort.** Small per pack once the content exists. The work is **content,
not code**: writing original paraphrases of each control objective.

**The hard part — copyright.** The README already carries the right position
("control IDs and short titles are functional identifiers; the `objective`
fields are brief original paraphrases"). Selling packs raises the stakes:

- **NIST 800-53** — US Government work, public domain. Safe to ship verbatim.
  Start here. Rev 5 is ~1000 controls; consider shipping the moderate
  baseline rather than everything.
- **HIPAA Security Rule** — the regulation text is public domain (45 CFR
  §164.308–318). Safe. High commercial demand.
- **SOC 2 Type II** — the Trust Services Criteria are **AICPA copyright**.
  You already ship a paraphrased SOC 2. Selling it needs either a licence
  from the AICPA or confidence in the paraphrase. Get a lawyer's opinion
  before it becomes a paid SKU; this is the one with real exposure.
- **ISO 42001 / ISO 27017** — ISO standards are **sold** by ISO and national
  bodies and are aggressively protected. You cannot redistribute the control
  text. A pack can ship control *identifiers* and your own objectives, and
  should say plainly that the customer must hold a licence for the standard.
  Same position as the existing ISO 27001 pack.

**Recommendation.** Ship NIST 800-53 and HIPAA first: public domain, no legal
tail, immediate value. Treat the ISO packs as identifier-plus-paraphrase and
price them lower. Get advice on SOC 2 before selling it separately.

**Also worth building alongside:** a pack *authoring* format so a customer
can add their own internal framework. That is a feature nobody can pirate
because it is about their content, not yours.

---

## 2. Meeting scheduler — Teams and Google Meet

**What it is.** Create the meeting from inside the cadence tracker, so a
quarterly security-committee meeting produces a real calendar invite.

**Where it lands.** `governance/models.py` already has `MeetingSeries`
(with `required_per_year`) and `MeetingMinute`. `calendar_app` holds
`CalendarEvent`. The natural shape:

- `MeetingSeries.schedule` — an RRULE plus a default duration and attendee
  list (reuse `ChampionGroup` membership as the invitee source).
- A `MeetingLink` model holding the provider, the external event id, the join
  URL and the OAuth credential used.
- `POST /api/meeting-series/{id}/schedule/` creates the external event and
  writes back the join URL; a webhook or a poll reconciles cancellations.

**Effort.** Medium, and the effort is almost entirely **OAuth and token
lifecycle**, not calendaring. Microsoft Graph (`Calendars.ReadWrite`,
`OnlineMeetings.ReadWrite`) and Google Calendar (`calendar.events` with
`conferenceData`) both need a registered app, a consent flow, refresh-token
storage and re-consent handling. You already have `config/fieldcrypto.py`
for encrypting stored tokens at rest — use it, with the AAD bound to the row.

**Watch out.** A self-hosted customer needs *their own* OAuth app
registration, or you become the data processor for every customer's calendar.
Document the app-registration steps; do not ship your client secret.

---

## 3. In-app assistant — "what do I do, where does this go"

**What it is.** A chat box that answers programme questions: which control
this policy satisfies, what evidence an auditor expects for CC6.1, what is
overdue and why.

**Where it lands.** This is the feature with the **best fit to what you
already have** and the one to be most careful with.

The retrieval corpus is unusually good: 217 controls with objectives, the
crosswalk, every document's name, control links, review state, the risk
register, the vendor matrix. A RAG index over *metadata* is high-value and
low-risk. Indexing **document contents** is a different proposition — that
is the customer's evidence, often containing PII and secrets.

**Recommended shape:**

- **Bring your own key.** The customer supplies an API key (or points at a
  local model). You ship the retrieval and the prompt; they choose the
  provider. This sidesteps the entire data-processing question for
  self-hosted installs and is consistent with the product's posture.
- Retrieve over **metadata first**, and make document-content indexing an
  explicit per-folder opt-in with a visible indicator.
- The answer must **cite** — control ref, document name, link. An unsourced
  answer in a compliance tool is a liability, not a feature.
- **Never let it write.** Read-only, suggestions only. An assistant that can
  mark a control implemented is an audit-trail problem.
- Scope every retrieval to the caller's workspace *and* their folder
  permissions. The 0.9.0 tenancy layer gives you the first half; the second
  half is `documents/access.py:accessible_folder_ids`. Getting this wrong
  turns the assistant into a permission-bypass oracle — treat it as the
  highest-risk code in the product and test it like the tenancy layer.

**Effort.** Medium for metadata RAG with citations. Large if you index
content (chunking, embeddings storage, re-index on version bump, deletion
propagation when a document is removed).

---

## 4. DocuSign — in-app signing and signature notification

**What it is.** Send a policy for signature, track it, file the signed copy
as evidence automatically.

**Where it lands.** This one is a genuinely good fit for the evidence model,
because a signed policy *is* the evidence auditors ask for.

- A `SignatureRequest` model: document, envelope id, recipients, status,
  sent/completed timestamps.
- `POST /api/documents/{id}/send_for_signature/`.
- A **webhook receiver** (DocuSign Connect) that, on completion, downloads
  the signed PDF and files it as a new `DocumentVersion` with the
  certificate of completion attached.
- The tray and the Slack/Teams channel already exist — signature events slot
  straight into `notifications/webhooks.py` `EVENTS`.

**Effort.** Medium. The webhook is the interesting part: it is a **new
unauthenticated endpoint**, which this review has just shown is the riskiest
category in the product. It must verify DocuSign's HMAC signature, be
replay-resistant, and resolve the workspace from the envelope rather than
from a request context (there is no user). Model it on
`vendors/public_views.py` and be stricter.

**Alternative worth costing:** the same shape works for Dropbox Sign or a
self-hosted signing flow. DocuSign is expensive per envelope; a customer may
already have a contract, so make the provider pluggable from day one.

---

## 5. Contract auto-extract — client register of standards with expiry

**What it is.** Upload a signed contract; an AI reads it and fills in the
vendor record, the standards the counterparty is held to, and the expiration
date, which then feeds the existing review clock.

**Where it lands.** `vendors/models.py` already has `Vendor` with a review
cadence, `VendorAssessment` with validity windows and expiry tracking, and
`SharedResponsibility`. The extraction writes into records that already
exist, which is why this is attractive.

- `POST /api/vendors/{id}/extract/` — accepts the contract, returns a
  **proposed** record.
- **Never write directly.** Mirror the pattern the matrix importer already
  uses: "nothing is written until you confirm what it read." That existing
  UX is exactly right for this and should be reused, not reinvented.
- Store the extraction with a confidence and a pointer to the source span so
  a reviewer can check it.

**Your instinct about self-install is correct, and worth stating in the
product.** A signed contract is one of the most sensitive documents a
customer holds — pricing, counterparties, termination terms. Sending it to a
third-party model is a decision the customer must make explicitly.

- **Self-hosted + bring-your-own-key:** the customer's contract goes to the
  customer's chosen provider under the customer's terms. Clean.
- **Hosted:** you are now processing your customers' contracts. That needs an
  explicit retention policy, a DPA, sub-processor disclosure, and a deletion
  guarantee you can actually honour. Say the retention period in the UI at
  the moment of upload, not in a policy page nobody reads.

**Effort.** Medium for the extraction; the review-and-confirm UI is most of
the work. Accuracy on real contracts is the risk — budget for a evaluation
set of real (redacted) contracts before promising a number.

---

## 6. PII extraction and masking

**What it is.** Find personal data in uploaded evidence; optionally mask it.

**Where it lands.** `documents/` — the same seam as malware scanning, which
is the right precedent: `scan_or_raise` runs on upload, and there is already
a quarantine state, a health probe and a re-scan sweep to copy.

- A `PiiFinding` model per document: type, count, location, detected-at.
- Run on upload and on a sweep, exactly like `documents/monitor.py`.
- Surface as a badge in the document list and a per-folder summary.

**Masking is the hard half, and needs a decision.** Masking evidence
*destroys* it — a redacted screenshot may no longer prove the control. Two
coherent products:

1. **Detect and warn** (build this first). "This upload appears to contain 14
   national insurance numbers." The customer decides. Low risk, immediately
   useful, no evidence destroyed.
2. **Masked derivative for the auditor.** Keep the original; generate a
   masked copy that goes into the audit package instead. This fits the
   package model well — the manifest already records a digest per member, so
   a masked member is honestly recorded as what was disclosed. Note it
   changes what "the evidence" means and must be visible in the bundle.

**Do not mask in place.** Silent modification of evidence would undermine the
integrity story the whole product is built on.

**Effort.** Medium for detection (Presidio is the obvious starting point, but
it is a heavy dependency for a stdlib-proud codebase — consider a regex-plus-
checksum core for the high-value identifiers and make the ML detector
optional). Large for masking, mostly in the PDF and image paths.

---

## Suggested order

| Order | Feature | Why first |
|---|---|---|
| 0 | Plugin seam + offline licence | Everything else depends on it |
| 1 | NIST 800-53 and HIPAA packs | Content-only, no legal tail, sells immediately |
| 2 | PII **detection** (no masking) | Reuses the scanner seam, no evidence risk |
| 3 | Assistant over metadata, BYO key | Best fit to existing data, high demo value |
| 4 | DocuSign | High willingness to pay; needs a hardened webhook |
| 5 | Contract extract | Depends on the assistant's plumbing |
| 6 | Meeting scheduler | Most OAuth grind for least differentiation |
| 7 | ISO packs, SOC 2 pack | Gated on legal advice |

## Open questions

1. Open core, hosted, or both? Everything above branches on this.
2. Is the paid tier **per workspace** or **per installation**? The 0.9.0
   tenancy model makes per-workspace entitlement natural, and it is how a
   consultancy running many clients would want to buy.
3. Who holds the AI provider key — customer or you? Recommended: customer.
4. Is there a hosted offering at all? If yes, the retention and DPA work in
   §5 is a prerequisite, not a follow-up.
