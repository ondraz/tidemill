---
title: Log
description: Append-only chronological record of every ingest, query, and lint pass.
type: meta
updated: 2026-07-23
---

# Log

> Append-only. Newest entries at the bottom. Every entry starts with
> `## [YYYY-MM-DD] <op> | <subject>` so the history stays greppable:
>
> ```bash
> grep "^## \[" docs/wiki/log.md | tail -5
> ```
>
> Operations: `ingest`, `query`, `lint`.

---

## [2026-07-23] lint | Wiki bootstrap

**Op:** Initial build of the LLM wiki layer under the existing MkDocs site.

**Created:**

- `how-it-works.md`, `index.md` (catalog), `log.md` (this file)
- 10 entity pages: Tidemill, ChartMogul, Baremetrics, ProfitWell, SaaSGrid,
  Stripe Billing, Chargebee, Lago, Kill Bill, QuickBooks Online
- 8 concept pages: MRR, Churn, Net Revenue Retention, Cohort Retention, LTV,
  Usage-Based Pricing, Trial Conversion, Metric Transparency
- `sources/README.md` — raw layer conventions and capture backlog
- `.claude/skills/llm-wiki/SKILL.md` — the schema, referenced from `AGENTS.md`

**Compiled from:** the seven existing `docs/research/` documents (last updated March 2026),
`docs/definitions.md`, and the `docs/architecture/` specifications. No new external
sources were fetched — this pass reorganised knowledge already in the repository into
entity and concept pages, and designated the research documents as the synthesis layer.

**Findings:**

1. **Stale status labels in `definitions.md`.** LTV and Trial Conversion Rate are filed
   under *"Planned (P1) — designed but not yet implemented"*, but `tidemill/metrics/ltv/`
   and `tidemill/metrics/trials/` both ship and are registered. `AGENTS.md` correctly
   lists them as implemented, so the two documents contradict each other. The formulas in
   `definitions.md` are current; only the status heading is wrong. Flagged inline on
   [LTV](concepts/ltv.md) and [Trial Conversion](concepts/trial-conversion.md).
   **Not auto-corrected** — restructuring `definitions.md` needs a human call on whether
   Quick Ratio (also under that heading) is genuinely unimplemented.

2. **Chargebee undocumented in the architecture docs.** `tidemill/connectors/chargebee/`
   is implemented and enabled in production, and appears throughout
   `canonical-vocabulary.md`, but `connectors.md` documents only Stripe, Lago, Kill Bill
   and QuickBooks. `AGENTS.md` names it a secondary revenue connector without a section of
   its own. Recorded on [Chargebee](entities/chargebee.md).

3. **Raw source layer is empty.** The wiki was bootstrapped from compiled research rather
   than from captured sources, so ~33 URLs cited across `docs/research/` have no source
   record. Tracked in `sources/README.md`. Every claim in the wiki traceable to those
   citations currently cites the research document rather than the original.

4. **Two concept gaps, both acknowledged in existing docs.** Cohort-level *revenue*
   retention (ChartMogul has it, Tidemill does not) and CAC (blocked on acquisition-spend
   data). Neither has a page yet; both are recorded as contested ground on
   [Cohort Retention](concepts/cohort-retention.md) and [LTV](concepts/ltv.md).

**Next:** capture raw sources for the highest-traffic citations (competitor pricing pages
go stale fastest — every pricing claim in the wiki is dated *as of March 2026*), and
decide on the `definitions.md` status-heading correction.

## [2026-10-25] ingest | Provider API changes — Stripe Dahlia/Endive, Chargebee 2026, QBO minor version 75

**Sources:** `sources/2026-10-25-stripe-python-changelog.md`,
`sources/2026-10-25-chargebee-python-changelog.md`,
`sources/2026-10-25-intuit-qbo-minor-versions.md` (referenced only)
**Updated:** [Stripe Billing](entities/stripe-billing.md),
[Chargebee](entities/chargebee.md), [QuickBooks Online](entities/quickbooks-online.md),
[Usage-Based Pricing](concepts/usage-based-pricing.md)
**Also changed (code + specs):** `tidemill/connectors/stripe/connector.py`,
`tidemill/connectors/quickbooks/client.py`, `deploy/seed/quickbooks_seed.py`,
`architecture/connectors.md`, `architecture/events.md`,
`architecture/canonical-vocabulary.md`; stripe SDK floor raised to 16.0.0
(pins `2026-09-30.endive`).

**Findings:**

1. **Stripe Endive adds on-demand pause/resume.** Before Endive, the connector mapped
   `paused` → `active` to `subscription.activated`, so a resumed customer could be
   booked as *new* MRR. It now reads `status_details.paused.subscription.type` and emits
   `subscription.resumed` (reactivation) unless the pause came before any payment.
   Fixed in code.
2. **Contradiction: "Stripe metering is pre-aggregated only."** Stripe ingests
   event-level meter events but exposes only aggregated summaries to readers. Flagged
   on [Stripe Billing](entities/stripe-billing.md) and reworded in
   [Usage-Based Pricing](concepts/usage-based-pricing.md). **Not reconciled** in
   `research/billing-engines.md` or `research/competitive-matrix.md`; the synthesis
   layer needs a human call.
3. **QBO `minorversion=65` was dead weight.** Intuit has ignored values below 75 since
   2025-08-01. Pinned to 75. Fixed.
4. **Chargebee changes are additive** for subscriptions and invoices, so no connector
   change was needed. Not acted on: `Subscription.decommissioned` (semantics unknown,
   might need excluding from metrics), invoice `exchange_rates`, omnichannel
   (app-store) subscriptions and the credits ledger — all un-ingested.
5. **Not acted on — Stripe:** item-level trials (`current_trial`) are not read, and trial
   analytics still uses the subscription-level `trial_end`.
   `invoice.status_details.uncollectible.reason` is not read. A `trialing` → `paused`
   transition (trial ended without a payment method) still emits `subscription.paused`,
   which the MRR metric books as a churn movement for a subscription that never
   activated. This bug predates the ingest and is not fixed. Backfill emits no pause
   event for subscriptions already `paused`.
6. **Not captured:** Stripe `clover` (2025-09-30), Lago and Kill Bill release notes, and
   competitor pricing. Vendor sites and GitHub release pages were blocked by the capture
   environment. Lago and Kill Bill are unimplemented, so nothing in code is affected.
7. **Lint fix:** `architecture/expenses.md` linked a non-existent `connectors.md` anchor.
   Repointed to the QuickBooks section.

