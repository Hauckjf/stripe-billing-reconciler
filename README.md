# Stripe Billing Reconciler

![CI](https://github.com/Hauckjf/stripe-billing-reconciler/actions/workflows/ci.yml/badge.svg) ![License](https://img.shields.io/github/license/Hauckjf/stripe-billing-reconciler?color=blue) ![Last commit](https://img.shields.io/github/last-commit/Hauckjf/stripe-billing-reconciler)

> Reconcile Stripe charges and subscriptions against your internal orders table — cursor-paginated, idempotent, rate-limit-aware, and auditable.

CLI tool written in Python — chosen for scripting ergonomics and Stripe SDK maturity — that fetches Stripe charge and subscription events via cursor-based pagination, cross-references them against a local orders table (columns: order_id TEXT, amount_cents INTEGER, stripe_charge_id TEXT, created_at TIMESTAMP), and outputs a structured discrepancy re

## Table of contents

- [About](#about)
- [Tech](#tech)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

## About

CLI tool written in Python — chosen for scripting ergonomics and Stripe SDK maturity — that fetches Stripe charge and subscription events via cursor-based pagination, cross-references them against a local orders table (columns: order_id TEXT, amount_cents INTEGER, stripe_charge_id TEXT, created_at TIMESTAMP), and outputs a structured discrepancy re

**What this demonstrates**

- Cursor-based pagination over Stripe Events API with auto-resume on interrupted runs via SQLite checkpoint table
- Token-bucket rate limiter to stay within Stripe's 100 req/s limit without 429 errors
- Idempotent rerun via checkpoint table storing last-processed event cursor in SQLite
- Discrepancy classification engine with configurable tolerance window operating against a typed orders schema (order_id, amount_cents, stripe_charge_id, created_at)
- Structured JSON logging with per-run correlation IDs for auditability
- Full static analysis pipeline: mypy strict-mode type checking + ruff linting + pytest ≥85% line coverage enforced in GitHub Actions CI on every push

## Tech

Python · Stripe SDK · SQLite · Click · pytest · mypy · ruff · GitHub Actions

## Installation

```bash
git clone https://github.com/Hauckjf/stripe-billing-reconciler.git
cd stripe-billing-reconciler
# install dependencies
```

## Usage

_Examples coming with the first feature release._

## Architecture

_High-level diagram and decision records in `docs/`._

## Definition of done

- Fetches all charges and subscription invoices for a configurable date range using cursor pagination; resumes an interrupted run from the last SQLite checkpoint without reprocessing already-seen events.
- Respects Stripe rate limits via token-bucket throttler; no 429 responses observed when running against a Stripe test-mode account with default concurrency settings.
- Orders table contract: tool expects columns order_id TEXT, amount_cents INTEGER, stripe_charge_id TEXT, created_at TIMESTAMP; accepts an alternate table name via --schema flag; a migrations script is included to create the table from scratch.
- Outputs a JSON report with three top-level arrays — matched, unmatched, amount_mismatched — each entry including stripe_charge_id, order_id (if found), expected_amount_cents, actual_amount_cents, and delta_cents.
- CLI accepts --from (ISO date), --to (ISO date), --output (file path, default stdout), --tolerance (int cents, default 0), --threshold (max unmatched count before non-zero exit, default 0), --mock (offline run against bundled fixtures), --schema (alternate orders table name); exits non-zero when unmatched count exceeds --threshold.
- pytest suite achieves ≥85% line coverage enforced via pytest-cov --fail-under=85; suite covers cursor resume logic, each discrepancy classification rule, token-bucket refill timing, and all CLI flag combinations.
- --mock flag loads bundled fixtures/stripe_events.json (50 charges, 10 subscription invoices) and fixtures/orders.csv and runs the full reconcile pipeline end-to-end without a live Stripe key; README Quick Start section uses this flag with truncated sample output.
- mypy --strict passes with zero errors; ruff check passes with zero warnings; both run as required steps in the GitHub Actions CI workflow and block merge on failure.
- README covers five sections: Installation (pip install -e . with Python ≥3.11 requirement), Quick Start (copy-paste --mock command with truncated JSON output), Configuration (STRIPE_API_KEY and DATABASE_URL env vars with SQLite default), Output schema (annotated JSON example with all three report arrays), and Limitations (no webhook ingestion, Stripe Connect accounts not tested, charge refunds counted as unmatched).

## Contributing

See [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## License

[MIT](LICENSE)

---

<sub>Part of [@Hauckjf](https://github.com/Hauckjf)'s portfolio.</sub>

<sub>Built with [Claude Code](https://claude.com/claude-code) — reviewed, tested, and maintained by [@Hauckjf](https://github.com/Hauckjf).</sub>
