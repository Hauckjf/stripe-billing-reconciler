# AI-assisted development

This repository is built with AI assistance for some specific tasks. This
document is the canonical, transparent record of where AI was and was not
used — so anyone reviewing the codebase knows exactly what to weight.

## Tools used

- **Claude (Anthropic)** — primary AI assistant; invoked via Claude Code CLI
  for documentation drafting, ADR co-authoring, and code-review style passes.

## Where AI contributed substantively

These artifacts were drafted with Claude in the loop, then human-edited
before commit. The corresponding commits carry a
`Co-Authored-By: Claude` trailer:

- `docs/adr/0001-sqlite-for-local-orders-store.md`
- `docs/adr/0002-cursor-based-pagination.md`
- `docs/adr/0003-cli-and-data-model-choices.md`
- `docs/adr/0004-ai-assisted-documentation.md`
- `docs/ai-assisted-development.md` (this file)
- Sections of `README.md` (architecture diagram, discrepancy-kinds table)
- Sections of `CHANGELOG.md` (entry phrasing)
- Sections of `CONTRIBUTING.md` (AI-assisted-contributions section)

When Claude contributed substantive prose to a commit, that commit's message
ends with:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

This is the same pattern GitHub uses for human pair-programmers — it
attributes the contribution honestly without hiding it.

## Where AI did NOT contribute

The core implementation is human-authored:

- All `.py` files under `src/stripe_reconciler/` — module structure,
  function bodies, type signatures, error handling, retry strategy,
  pagination loop, discrepancy classifier, SQLite schema, CLI wiring
- All `.py` files under `tests/` — test design and assertions
- All design decisions captured in the ADRs (the ADRs document
  decisions that were already made before drafting)
- The `pyproject.toml` configuration choices
- The Stripe API integration points and the choice of `tenacity` for retry

In short: **the code is mine. The prose is sometimes co-authored with Claude.**

## Why this matters

Two reasons to be explicit about this:

1. **Credit attribution.** If Claude drafted text in a commit, the commit
   message says so. This matches the contribution policy GitHub already
   surfaces via the `Co-Authored-By:` trailer convention.
2. **Reviewer calibration.** A reviewer evaluating this codebase as a work
   sample should weight implementation decisions (code, architecture,
   trade-offs) as my own, and weight prose polish (READMEs, ADRs) as a
   collaborative product. That's a fair read of how modern senior engineering
   workflows actually look.

## Boundaries

A few things AI is **not** used for in this repo:

- Generating tests that the reviewer would mistake for human-authored
  (every test in `tests/` reflects my own design intent, even if some
  assertion phrasing was polished afterward)
- Writing commit messages on behalf of changes I didn't review
- Reviewing PRs (this is a solo repo, no PR review happens)
- Generating production-bound code without my line-by-line review

The principle: AI accelerates documentation cycles. It does not substitute
for engineering judgement.
