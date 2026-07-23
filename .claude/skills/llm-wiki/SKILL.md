---
name: llm-wiki
description: Build and maintain Tidemill's compounding knowledge wiki in docs/wiki/ — entity and concept pages compiled from raw sources, plus a catalog and an append-only log. Use when ingesting a new source (article, pricing page, competitor doc, report, changelog, transcript), when answering a question about competitors, the market, billing engines, or metric definitions, when filing a useful answer back into the wiki, or when linting for contradictions, stale claims, orphan pages, and missing cross-references. Triggers on "ingest this", "add this source", "what do we know about X", "update/lint the wiki", and questions about ChartMogul, Baremetrics, ProfitWell, SaaSGrid, Stripe Billing, Chargebee, Lago, Kill Bill, QuickBooks Online, or how a metric is defined.
---

# LLM Wiki

You maintain a persistent, interlinked knowledge base — not a chat history. Knowledge is
**compiled once and kept current**, so every source and every good answer makes the wiki
richer instead of evaporating.

The human curates sources, directs analysis, and asks questions. You do the reading,
summarising, cross-referencing, filing, and bookkeeping. The bookkeeping is the point:
it is what humans abandon and what you can do without tiring.

Concept and rationale: `docs/wiki/how-it-works.md`.

## Layout

```
docs/wiki/
├── how-it-works.md      Human-facing explanation of the system
├── index.md             THE CATALOG — every page, one line each
├── log.md               Append-only chronological record
├── entities/            One page per company, product, or system
├── concepts/            One page per recurring domain idea
└── sources/             RAW LAYER — read-only, excluded from the built site
```

Also in scope, but **not** rewritten from sources:

- `docs/research/` — the **synthesis layer**. Narrative pages that argue a position by
  linking out to entity and concept pages rather than restating their facts.
- `docs/architecture/`, `docs/development/`, `docs/definitions.md` — hand-authored
  **specifications**. Keep them consistent and cross-referenced; do not restructure them
  from sources. `definitions.md` is the authority for metric formulas.

## Hard rules

1. **Never edit anything in `sources/`.** It is the immutable input layer.
2. **Never restate a formula that `definitions.md` owns.** Link to it. Two copies drift,
   and drift in metric definitions is the exact failure this project exists to prevent.
3. **Record contradictions, do not silently resolve them.** When a new source disagrees
   with an existing claim, keep both with dates and flag it. A human decides.
4. **Date anything that can go stale** — pricing especially. Write "*(as of March 2026)*"
   inline, never "recently" or "currently".
5. **Cite claims.** A factual claim links to its source page or URL. Mark inference as
   inference.
6. **Every structural change updates `index.md` and appends to `log.md`.** No exceptions —
   an unlogged change is how the wiki starts rotting.

---

## Operation: Ingest

A new source arrives. Process it end to end:

1. **Read** the source in `sources/`. If the human gave you a URL instead, fetch it and
   write a source record first (naming and frontmatter below).
2. **Discuss takeaways** with the human before writing. Ingest is collaborative — surface
   what is new, what is surprising, and what conflicts with existing pages. Do not
   silently batch-write a dozen pages.
3. **Identify affected pages.** A single source typically touches 3–15 pages. Search the
   wiki for every entity and concept it mentions — do not rely on the catalog alone.
4. **Update entity and concept pages.** New facts, revised claims, refreshed dates. Where
   the source contradicts an existing claim, keep both:

   ```markdown
   Pricing starts at $108/mo *(as of March 2026)*.

   !!! warning "Contradiction"
       [2026-07-23 pricing page](../sources/2026-07-23-baremetrics-pricing.md) shows
       $129/mo. Not yet reconciled.
   ```

5. **Create pages that are now warranted.** A concept mentioned across three or more
   sources deserves its own page instead of repeated inline explanation.
6. **Fix cross-references.** New page → link it from related pages. Every page needs at
   least one inbound link, or it is an orphan.
7. **Update `index.md`** — add or revise the row, reusing the page's `description`
   frontmatter verbatim as the summary.
8. **Add to MkDocs nav** in `docs/mkdocs.yml` under `Wiki:` if you created a page.
9. **Append to `log.md`.**
10. **Verify:** `uv run mkdocs build --strict -f docs/mkdocs.yml`.

## Operation: Query

Answer from the wiki, not from raw sources:

1. **Read `index.md` first**, then drill into the pages that look relevant. This is the
   retrieval mechanism — it works well up to a few hundred pages, so there is no embedding
   infrastructure to maintain.
2. **Answer with citations**, linking the wiki pages you used.
3. **Say when the wiki does not know.** Do not fill a gap with generic knowledge and
   present it as accumulated knowledge. Offer to research it instead.
4. **File good answers back.** A comparison, an analysis, a connection worth keeping
   becomes a page — then update `index.md` and `log.md`. This is what makes exploration
   compound rather than evaporate. Ask before filing if it is a judgement call.

## Operation: Lint

A periodic health check. Report findings; fix the mechanical ones; ask before anything
judgement-laden.

Check for:

- **Contradictions** — pages disagreeing on a fact
- **Stale claims** — dated facts older than ~6 months, especially competitor pricing;
  sources marked `status: stale`
- **Doc drift** — wiki or docs claims that no longer match the code (status labels,
  implemented-vs-planned, file paths that moved)
- **Orphans** — pages with no inbound links
- **Missing pages** — concepts referenced repeatedly with no page of their own
- **Three-way drift** — the page set on disk, the rows in `index.md`, and the `Wiki:`
  section of `docs/mkdocs.yml` nav must agree
- **Broken links** — `uv run mkdocs build --strict -f docs/mkdocs.yml`
- **Uncaptured sources** — citations with no record in `sources/` (see its README backlog)

Useful starting points:

```bash
grep "^## \[" docs/wiki/log.md | tail -5                    # recent activity
ls docs/wiki/entities docs/wiki/concepts                    # actual page set
grep -c "wiki/" docs/mkdocs.yml                             # nav entry count
grep -roh "](\.\./[a-z-]*/[a-z0-9-]*\.md)" docs/wiki/       # internal link targets
```

Fix without asking: broken links, missing catalog rows, missing nav entries, absent
cross-references. Ask first: resolving a contradiction, deleting a page, restructuring a
specification, or correcting a hand-authored doc like `definitions.md`.

Always append the pass to `log.md`, including findings you did **not** act on.

---

## Page conventions

**Frontmatter** on every page. `description` is the one-liner reused verbatim in the
catalog, so make it a complete, informative sentence.

```yaml
---
title: ChartMogul
description: Closed-source subscription analytics platform; the depth leader in segmentation.
type: entity          # entity | concept | meta | source
tags: [analytics-tool, competitor, closed-source]
updated: 2026-07-23
---
```

**Links** are relative and end in `.md` — they resolve both on the docs site and on GitHub.
From `entities/` or `concepts/`, reach other docs with `../../architecture/metrics.md`.

**Filenames** are kebab-case, singular, matching the subject: `kill-bill.md`,
`net-revenue-retention.md`.

**Voice** matches the rest of `docs/`: a `>` blockquote summary under the H1, `---` between
major sections, tables for structured facts, admonitions (`!!! note`, `!!! warning`) for
flags. Prose over bullet soup — explain *why* something matters, not just what it is.

### Entity template

```markdown
# <Name>
> One-line characterisation.
---
## What it is
## Key facts          <!-- table: category, licence, pricing (dated), data access, status -->
## Strengths
## Limitations
## Relevance to Tidemill    <!-- the section that earns the page's existence -->
## Related
## Sources
```

### Concept template

```markdown
# <Concept>
> One-line definition.
---
## The idea
## Why it matters
## How Tidemill computes it   <!-- link definitions.md for formulas, never copy them -->
## Contested ground           <!-- where reasonable people disagree; the most valuable section -->
## Related
## Sources
```

### Source record

`sources/YYYY-MM-DD-slug.md`, dated by capture. Full frontmatter spec and the current
capture backlog: `docs/wiki/sources/README.md`.

## Log format

Append to the bottom. Fixed prefix keeps the file greppable:

```markdown
## [2026-07-23] ingest | ChartMogul 2026 pricing update

**Source:** `sources/2026-07-23-chartmogul-pricing.md`
**Updated:** [ChartMogul](entities/chartmogul.md), [MRR](concepts/mrr.md)
**Created:** [Quick Ratio](concepts/quick-ratio.md)
**Findings:** Scale tier moved $100 → $129 per $10K MRR; contradicts the March 2026 figure
in `research/analytics-tools.md`, flagged on the entity page, not reconciled.
```

Ops are `ingest`, `query`, or `lint`. Record findings you did not act on — the log is the
memory of what was noticed, not only of what was changed.
