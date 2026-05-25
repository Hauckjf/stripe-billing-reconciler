# ADR-0004: AI-assisted documentation, with attribution

## Status

Accepted — 2026-05-25.

## Context

Maintaining substantive documentation across README, CHANGELOG, ADRs, and
contributor guides is time-consuming, and the cost-per-revision is high
relative to the size of a hobby/career-demo project. At the same time,
documentation drift is the single most common reason public repositories
look unprofessional — claims diverge from the code, links rot, scaffolding
text never gets replaced.

Two options were considered for how to keep documentation current without
spending more hours on prose than on implementation.

### Option A — Human-only documentation

Every word in every doc is human-written from scratch. Highest signal of
authorship; lowest velocity. Realistic outcome for a side project: docs
become stale because writing them is friction, and the project ends up
under-documented (which was the actual previous state of this repo — the
ADRs were stubs, CHANGELOG referenced non-existent features, README
contradicted the source).

### Option B — AI-assisted documentation, with explicit attribution

Use an AI assistant (Claude, via the Claude Code CLI) to draft and refine
documentation. Every commit where AI contributed substantively carries a
`Co-Authored-By: Claude <noreply@anthropic.com>` trailer — the same
attribution convention GitHub already supports for human pair-programmers.

The implementation code stays human-authored; AI is scoped to prose.

### Option C — AI-assisted documentation, undeclared

Use AI but don't surface it in commit metadata. Higher velocity than A,
same as B, but hides the workflow. Rejected because the attribution is
cheap to include and asymmetric: omitting it looks like an oversight if
spotted, including it looks like good practice. The downside of disclosing
is essentially zero in 2026; AI-pair-programming for docs is now industry
norm.

## Decision

Choose **Option B**.

Concretely:

1. AI assistance is **scoped to prose**: ADRs, README sections, CHANGELOG
   wording, CONTRIBUTING guidance, blog post drafts. Not implementation
   code, not tests, not commit messages on changes I didn't review.
2. Every commit where AI contributed substantively to the diff carries
   the `Co-Authored-By: Claude <noreply@anthropic.com>` trailer.
3. The full inventory of where AI was used is maintained in
   `docs/ai-assisted-development.md`, so a reviewer doesn't need to grep
   commit messages to know the scope.
4. AI output is **always human-reviewed** before commit. The AI does not
   commit on my behalf; I read the diff, edit where wrong, then commit.

## Consequences

### Positive

- **Documentation stays current.** The cost of updating a README after a
  refactor drops by an order of magnitude. The cost-of-staleness drops to
  near zero because keeping docs synced is no longer a major time sink.
- **Honest attribution.** Reviewers can weight contributions correctly.
  Prose that was drafted with AI assistance is marked; implementation that
  was not is unmarked. A reviewer evaluating this work as a code sample
  doesn't have to guess.
- **Signal of modern engineering practice.** Senior engineering in 2026
  involves knowing when and how to use AI tools effectively. Documenting
  the workflow openly is itself a signal of that competence.

### Negative / Trade-offs

- **The `Co-Authored-By` trailer shows the AI account (`@claude`) in the
  GitHub contributors widget.** This is the intended outcome of using the
  convention as designed — but it does mean a reader who only looks at the
  contributors sidebar might overestimate AI's role. Mitigation: this ADR
  and `docs/ai-assisted-development.md` exist so the actual scope is one
  click away.
- **AI-drafted prose can drift from code unless reviewed.** Mitigated by
  the human-review rule. Any commit landing on `main` was read line-by-line
  before push.
- **Some readers have a strong reaction to seeing AI attribution at all.**
  Acknowledged. The alternative (Option C, hiding the workflow) is worse
  on integrity, so this trade-off is accepted.
