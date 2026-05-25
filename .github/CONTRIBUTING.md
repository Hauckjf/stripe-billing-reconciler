# Contributing to stripe-billing-reconciler

Thank you for considering a contribution. This guide covers everything you need
to get the project running locally, run the full quality gate, and open a PR
that passes review on the first round.

---

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/Hauckjf/stripe-billing-reconciler.git
cd stripe-billing-reconciler
```

### 2. Pin the Python version with pyenv

The project targets Python 3.11+. If you use [pyenv](https://github.com/pyenv/pyenv):

```bash
pyenv install 3.11
pyenv local 3.11
```

Verify the active interpreter:

```bash
python --version
# Python 3.11.x
```

### 3. Install the package in editable mode with dev extras

```bash
pip install -e '.[dev]'
```

This installs the runtime dependencies (`stripe`, `pydantic`, `click`, `rich`,
`tenacity`) **and** the dev toolchain (`pytest`, `pytest-cov`, `mypy`, `ruff`,
`pytest-httpx`, `freezegun`) declared in `pyproject.toml`.

Confirm the CLI entry point is on your PATH:

```bash
stripe-reconcile --help
```

Expected output (truncated):

```
Usage: stripe-reconcile [OPTIONS] COMMAND [ARGS]...

  Stripe Billing Reconciler — cross-reference Stripe charges against your orders table.

Commands:
  reconcile  Fetch Stripe charges and events, cross-reference against local orders...
```

### 4. Set your Stripe API key

All integration paths require a key. Any Stripe test-mode key works — no live
charges are ever made.

```bash
export STRIPE_API_KEY=sk_test_...
```

You can also create a `.env` file at the project root; `pydantic-settings` will
pick it up automatically:

```
STRIPE_API_KEY=sk_test_...
```

---

## Running Tests

All commands below must pass before you open a PR. The CI pipeline runs the
same checks on every push.

### Unit and integration tests

```bash
pytest -v
```

Expected tail output on a clean run:

```
============= X passed in Y.Zs =============
```

### Tests with branch coverage

Coverage is configured in `pyproject.toml` and enforces a 70 % line threshold:

```bash
pytest --cov --cov-report=term-missing
```

The report highlights which lines are not exercised. If coverage drops below
70 %, the command exits non-zero — same behaviour as CI. The 70 % floor is
temporary while the CLI surface gets dedicated `CliRunner` tests; the goal is
to raise it back toward 85 % as those land.

### Static type checking

```bash
mypy src/
```

Mypy runs in `strict` mode (`disallow_untyped_defs`, `warn_return_any`,
`warn_unused_ignores`). Every public function must carry full type annotations;
private helpers should too.

### Linting

```bash
ruff check .
```

Ruff targets Python 3.11 with a curated rule set (`E`, `W`, `F`, `B`, `C4`,
`UP`, `SIM`, `PIE`, `RUF`, `PTH`) — production bug-catchers without
docstring/exception-style nits that fire on every other line. See
`[tool.ruff.lint]` in `pyproject.toml` for the exact `select` and `ignore`
lists; `tests/**` allows `assert` (B011) and `bench/**` allows `print`
(T201).

To auto-fix safe violations:

```bash
ruff check --fix .
```

---

## Making Changes

### Commit format

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

[optional body — explain the WHY, not the WHAT]
```

Allowed types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.

Examples:

```
feat(reconciler): classify DUPLICATE_CHARGE discrepancy kind
fix(fetcher): handle 429 rate-limit with exponential back-off
docs(contributing): add local dev setup section
```

- Subject ≤ 72 characters, lowercase, no trailing period.
- Use the body when the change has a non-obvious motivation (e.g. a Stripe API
  quirk, a tolerance edge case, a SQLite concurrency constraint).

### One logical change per PR

Keep PRs focused. A new discrepancy kind, a pagination fix, and a refactor of
the store layer each belong in separate PRs. Omnibus PRs are slow to review and
prone to merge conflicts.

### Tests are required for new code paths

Every new function or branch must be covered by at least:

- One happy-path test asserting the actual output.
- One edge-case test (empty input, boundary value, or expected error path).

Adding or modifying a public function without a corresponding test will cause
the coverage gate to fail in CI.

---

## Opening a PR

Before opening a pull request, run the full local gate:

```bash
pytest --cov --cov-report=term-missing   # coverage ≥ 85 %
mypy src/                                # zero errors
ruff check src/                          # zero violations
```

PR checklist — the reviewer will verify all of these:

- [ ] `pytest` passes with no failures.
- [ ] `pytest --cov` reports ≥ 70 % branch coverage (current floor — being raised
      back toward 85 % as CLI tests land).
- [ ] `ruff check .` exits with `All checks passed!`
- [ ] `CHANGELOG.md` has a bullet under `## [Unreleased]` describing the change
      (use the same Conventional Commit type as the commit message).
- [ ] The PR description explains **what** changed and **why**.
- [ ] No new `# type: ignore` comments unless unavoidable — add a comment
      explaining why the suppression is necessary if you must.
- [ ] If AI tools contributed substantively to the diff, the commit carries
      a `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. See
      [ADR-0004](../docs/adr/0004-ai-assisted-documentation.md) for the policy.

PRs that fail any CI check will not be merged until the gate is green.

---

## AI-assisted contributions

This project uses AI assistance (Claude, via Claude Code CLI) for **prose**:
README sections, ADRs, CHANGELOG entries, and this contributor guide. The
core implementation under `src/` and the test suite under `tests/` is
human-authored.

The convention follows GitHub's standard pair-programming attribution:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

Every commit where Claude contributed substantively to the diff includes
that trailer. The full inventory of where AI was used (and where it was
not) lives in [docs/ai-assisted-development.md](../docs/ai-assisted-development.md).
The rationale for the workflow is documented in
[ADR-0004](../docs/adr/0004-ai-assisted-documentation.md).

If you open a PR that uses AI tooling for any substantive part of the
change, follow the same convention — add the trailer in your commit
message. If your PR is human-only, no trailer is needed.

---

## Project Structure

All source lives under `src/stripe_reconciler/`. Here is a module-by-module map:

```
src/stripe_reconciler/
├── __init__.py          Public re-exports and package version
├── cli.py               Click command group and `reconcile` subcommand;
│                        parses flags, wires together all subsystems, sets exit code
├── client.py            Thin wrapper around the Stripe Python SDK;
│                        adds retry logic via tenacity and exposes a
│                        typed `get()` helper used by the fetchers
├── config.py            Pydantic-Settings `Settings` model; reads
│                        STRIPE_API_KEY from env or .env file
├── models.py            Typed data classes: `StripeCharge`, `LocalOrder`,
│                        `Discrepancy`, and the `DiscrepancyKind` enum
├── reconciler.py        Core cross-reference engine; consumes a list of
│                        `StripeCharge` objects and an `OrdersStore`,
│                        emits a list of `Discrepancy` objects
├── store.py             SQLite-backed `OrdersStore`; cursor-paginated reads,
│                        CSV import, and idempotent checkpoint tracking
├── formatters.py        `to_json`, `to_csv`, `to_table` — convert a list of
│                        `Discrepancy` objects to a formatted string
└── fetchers/
    ├── charges.py       Cursor-paginated fetch of `charge` objects from the
    │                    Stripe Charges API; resumes from SQLite checkpoint
    └── events.py        Cursor-paginated fetch of `invoice.payment_succeeded`
                         and related subscription events
```

`src/reconciler/` is a thin compatibility shim that re-exports the public API
so that the package can be imported as both `reconciler` and `stripe_reconciler`.

---

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](../LICENSE).
