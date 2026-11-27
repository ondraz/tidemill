---
title: QuickBooks Online Accounting API — minor versions 1–74 retired
url: https://blogs.intuit.com/?p=34635
publisher: Intuit
published: 2025-02-19
accessed: 2026-10-25
type: changelog
tags: [quickbooks-online, api-version, changelog]
status: referenced
---

# QuickBooks Online — minor versions 1–74 retired

Not captured: `blogs.intuit.com` was unreachable from the capture environment.
Claims below come from a search summary of Intuit's post, corroborated by the
[Codat notice](https://docs.codat.io/updates/250219-qbo-minor-versions-update)
and the [python-quickbooks PR](https://github.com/ej2/python-quickbooks/pull/381).
Re-capture from the primary source when possible.

- Effective **2025-08-01**, Intuit ended support for Accounting API minor versions 1–74.
- A request with `minorversion` below 75 has the value ignored and is answered as 75. An omitted `minorversion` also defaults to 75, not the base version.
- Future breaking changes (field or feature removals) ship as new minor versions. Additive schema fields do not bump the minor version.
- Not applicable to the Desktop, Payments or Payroll APIs.
