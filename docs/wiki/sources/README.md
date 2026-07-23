# Raw sources

The wiki's input layer. **Immutable** — the agent reads from these files and never edits
them. Everything here is tracked in git so any clone can re-read it, but MkDocs
`exclude_docs` keeps the whole directory off the published site (configured in
`docs/mkdocs.yml`), so Tidemill does not republish third-party material.

If you edit anything in here by hand, that is fine — you are the curator. The rule is that
the *agent* treats these as read-only.

---

## Naming

`YYYY-MM-DD-slug.md`, dated by capture, not publication:

```
2026-07-23-chartmogul-pricing.md
2026-07-23-lago-vs-stripe.md
```

## Format

```markdown
---
title: ChartMogul Pricing
url: https://chartmogul.com/pricing/
publisher: ChartMogul
author:                      # omit if none
published: 2026-03-01        # source's own date, if known
accessed: 2026-07-23         # when captured
type: pricing-page           # article | pricing-page | docs | report | changelog | transcript
tags: [chartmogul, pricing, competitor]
status: captured             # captured | referenced | stale
---

# ChartMogul Pricing

<!-- Captured content, or extracted claims with quotes. Verbatim where it matters. -->
```

`status` values:

- `captured` — content is in this file, agent can re-read it
- `referenced` — URL is cited by the wiki but content was never captured
- `stale` — known superseded; kept for the contradiction trail

## Adding a source

Drop the file in, then ask the agent to ingest it. It will read the source, update the
affected entity and concept pages, update `../index.md`, and append to `../log.md`.
See `.claude/skills/llm-wiki/SKILL.md` for the full workflow.

Two things worth doing as the curator:

- **Date every fact that can go stale.** Competitor pricing is the worst offender —
  every pricing claim in the wiki is currently marked *as of March 2026*.
- **Prefer primary sources.** A vendor's own pricing page beats a comparison blog post
  that cites it, and comparison posts written by competitors are not neutral.

---

## Capture backlog

**The wiki was bootstrapped from compiled research, not from captured sources.** The
seven documents in `docs/research/` (last updated March 2026) cite roughly 33 URLs between
them, none of which exist as source records here. Wiki claims traceable to those citations
currently cite the research document rather than the original.

This is the layer's main outstanding gap — recorded in the
[log](../log.md) on 2026-07-23. Highest value to capture first, because they go stale
fastest and the most wiki claims depend on them:

| Priority | Source | Cited by |
|---|---|---|
| 1 | [ChartMogul Pricing](https://chartmogul.com/pricing/) | `analytics-tools.md` |
| 1 | [Baremetrics Pricing](https://baremetrics.com/pricing) | `analytics-tools.md` |
| 1 | [Stripe Billing Pricing](https://stripe.com/billing/pricing) | `billing-engines.md` |
| 2 | [Paddle — ProfitWell Metrics](https://www.paddle.com/profitwell-metrics) | `analytics-tools.md` |
| 2 | [SaaSGrid](https://www.withgrid.com/) | `analytics-tools.md` |
| 2 | [Lago](https://getlago.com/) · [GitHub](https://github.com/getlago/lago) | `billing-engines.md` |
| 2 | [Kill Bill](https://killbill.io/overview) · [GitHub](https://github.com/killbill/killbill) | `billing-engines.md` |
| 3 | Market sizing reports (Juniper, Fortune Business Insights, Dimension) | `market-overview.md` |

Full citation lists live in the `## Sources` section of each research document.
