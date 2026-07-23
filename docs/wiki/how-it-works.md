---
title: How This Wiki Works
description: The three-layer LLM wiki — raw sources, LLM-maintained pages, and the schema that keeps the maintainer disciplined.
type: meta
updated: 2026-07-23
---

# How This Wiki Works

> Tidemill's knowledge base is an [LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
> a persistent, interlinked set of markdown pages that an LLM agent builds and
> maintains as new sources arrive. It is rendered by MkDocs like the rest of the docs.

---

## Why a wiki and not just documents

The usual pattern for LLMs and documents is retrieval: point the model at a folder,
let it find relevant chunks at query time, generate an answer, throw the answer away.
Nothing accumulates. Every question re-derives the same understanding from scratch.

This wiki inverts that. Knowledge is **compiled once and then kept current**. When a new
source arrives — a competitor's pricing page, a billing engine's changelog, a market
report — the agent reads it and integrates it: entity pages get updated, contradictions
with older claims get flagged, cross-references get rewritten, the catalog and log get
appended. A single source typically touches several pages.

The result is a compounding artifact. The cross-references already exist, the
contradictions have already been surfaced, and the synthesis already reflects everything
read so far.

The tedious part of running a knowledge base was never the reading — it was the
bookkeeping. That is the part the agent absorbs.

---

## The three layers

```
┌──────────────────────────────────────────────────────────────┐
│  SCHEMA        .claude/skills/llm-wiki/SKILL.md              │
│                Structure, conventions, and the three ops.    │
│                Read by the agent, co-evolved by humans.      │
└───────────────────────────┬──────────────────────────────────┘
                            │ governs
┌───────────────────────────┴──────────────────────────────────┐
│  WIKI          docs/wiki/                                    │
│                entities/  concepts/  index.md  log.md        │
│                Written and maintained entirely by the agent. │
│                Published to the docs site.                   │
└───────────────────────────┬──────────────────────────────────┘
                            │ compiled from
┌───────────────────────────┴──────────────────────────────────┐
│  RAW SOURCES   docs/wiki/sources/                            │
│                Immutable. The agent reads, never edits.      │
│                In git, but excluded from the published site. │
└──────────────────────────────────────────────────────────────┘
```

**Raw sources** are the input layer: captured articles, pricing pages, reports, release
notes. They are immutable — the agent reads from them and never rewrites them. They live
in git so any clone can re-read them, but MkDocs `exclude_docs` keeps them off the
published site so Tidemill does not republish third-party material.

**The wiki** is the agent's output. Humans read it; the agent writes it. Two page types
carry most of the weight:

| Directory | Holds | Example |
|---|---|---|
| `entities/` | A company, product, or system | [ChartMogul](entities/chartmogul.md) |
| `concepts/` | A domain idea that recurs across sources | [Net Revenue Retention](concepts/net-revenue-retention.md) |

Longer-form analysis lives in the existing [Research](../research/market-overview.md)
section, which acts as the wiki's **synthesis layer** — narrative pages that argue a
position by linking out to entity and concept pages rather than restating their facts.
[Architecture](../architecture/overview.md) and [Development](../development/development.md)
docs are in scope for the same maintenance and lint passes, but they remain hand-authored
specifications: they describe what Tidemill *does*, not what the wiki has *learned*.

**The schema** is `.claude/skills/llm-wiki/SKILL.md`. It defines page structure, naming,
frontmatter, link conventions, and the workflow for each operation. It is what makes the
agent a disciplined maintainer instead of a generic chatbot, and it is referenced from
`AGENTS.md` so every session picks it up automatically.

---

## The three operations

**Ingest** — a new source is added to `sources/` and the agent processes it: reads it,
discusses the takeaways, writes or updates the affected entity and concept pages, records
any contradiction with what the wiki already claimed, updates the catalog, and appends to
the log.

**Query** — a question is answered *from the wiki*, starting at the catalog rather than by
re-reading raw sources. When an answer turns out to be worth keeping — a comparison, a
newly-noticed connection — it gets filed back as a page so the exploration compounds
instead of evaporating into chat history.

**Lint** — a periodic health check: contradictions between pages, claims a newer source
has superseded, orphan pages nothing links to, concepts referenced everywhere but lacking
a page, and drift between the catalog, the MkDocs nav, and what is actually on disk.

---

## Navigating

**[Catalog](index.md)** is content-oriented — every page with a one-line summary, grouped
by category. It is the entry point for both humans and the agent; a query starts here and
drills down.

**[Log](log.md)** is chronological — an append-only record of every ingest, query, and lint
pass. Entries use a fixed prefix so the history stays greppable:

```bash
grep "^## \[" docs/wiki/log.md | tail -5
```

---

## Conventions

- **Frontmatter** on every page: `title`, `description`, `type`, `tags`, `updated`.
  `description` is the one-liner reused verbatim in the catalog.
- **Links** are relative and end in `.md` — they resolve on the docs site and on GitHub.
- **Claims carry citations.** A factual claim that came from a source links to that
  source's page or URL. Unsourced claims are marked as inference.
- **Dates are absolute** (`2026-07-23`), never "last month".
- **Contradictions are recorded, not silently resolved.** When a new source disagrees with
  an existing claim, both are kept with dates until a human decides.

The full, enforceable version of these rules lives in the schema.
