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
