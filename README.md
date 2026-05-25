# Stripe Billing Reconciler

[![CI](https://img.shields.io/github/actions/workflow/status/Hauckjf/stripe-billing-reconciler/ci.yml?branch=main&style=flat&label=CI)](https://github.com/Hauckjf/stripe-billing-reconciler/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat)](LICENSE) [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?style=flat)](https://www.python.org/downloads/) [![Coverage](https://img.shields.io/codecov/c/github/Hauckjf/stripe-billing-reconciler?style=flat)](https://codecov.io/gh/Hauckjf/stripe-billing-reconciler)

> Reconcile Stripe charges and subscriptions against your internal orders table — cursor-paginated, idempotent by design, retry-resilient on transient errors.

CLI tool written in Python — chosen for scripting ergonomics and Stripe SDK maturity — that fetches Stripe charges and subscription-related events via cursor-based pagination, cross-references them against a local orders table (columns: `order_id` TEXT, `amount_cents` INTEGER, `stripe_charge_id` TEXT, `created_at` TIMESTAMP), and outputs a structured discrepancy report.

## Table of contents

- [About](#about)
- [Tech](#tech)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Performance](#performance)
- [Contributing](#contributing)
- [License](#license)

## About

CLI tool written in Python — chosen for scripting ergonomics and Stripe SDK maturity — that fetches Stripe charges and subscription-related events via cursor-based pagination, cross-references them against a local orders table (columns: `order_id` TEXT, `amount_cents` INTEGER, `stripe_charge_id` TEXT, `created_at` TIMESTAMP), and outputs a structured discrepancy report.

**What this demonstrates**

- Cursor-based pagination over Stripe's Charges, Events, and Subscriptions list endpoints (via `starting_after` cursors, not offsets)
- `tenacity`-based retry with exponential backoff (multiplier=2, ceiling=60s) on `RateLimitError` and `APIConnectionError`; `AuthenticationError` is never retried
- Idempotent by design — stateless batch execution. `UNIQUE INDEX` on `stripe_charge_id` prevents duplicate orders import; in-memory dedup at the CLI orchestrator handles cross-source charge overlap (Charges API + subscription events stream)
- Typed `DiscrepancyKind` enum with four values — `AMOUNT_MISMATCH`, `CHARGE_NOT_IN_ORDERS`, `ORDER_NOT_IN_STRIPE`, `DUPLICATE_CHARGE_ID` — and configurable amount-tolerance window for multi-currency rounding
- Optional subscription enrichment (`--enrich-subscriptions`) appends subscription ID and status to relevant discrepancies without changing the `Discrepancy` schema
- Pure-domain classifier (`DiscrepancyClassifier`) does no I/O — testable in isolation, no DB fixture or HTTP mock required

## Tech

Python · Stripe SDK · SQLite · Click · pytest · mypy · ruff · GitHub Actions

## Installation

### Prerequisites

- **Python ≥ 3.11** — check with `python --version`
- **A Stripe restricted API key** with **read** access on **Charges** and **Subscriptions** — create one at [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/test/apikeys) (test-mode keys work; no live charges are made)

### Via pipx (recommended for end-users)

[pipx](https://pipx.pypa.io) installs the CLI in an isolated environment and puts `stripe-reconcile` on your `PATH` without polluting your global Python:

```bash
pipx install stripe-billing-reconciler
```

Verify the installation:

```bash
stripe-reconcile --version
```

### Via pip

```bash
pip install stripe-billing-reconciler
```

### Dev setup

```bash
git clone https://github.com/Hauckjf/stripe-billing-reconciler.git
cd stripe-billing-reconciler
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
```

Confirm everything is wired up:

```bash
pytest
```

All tests should pass. The suite runs against fixture data — no Stripe API key required.

## Usage

Set your Stripe API key before running:

```bash
export STRIPE_API_KEY=sk_test_...
```

Any [Stripe test-mode key](https://dashboard.stripe.com/test/apikeys) works; no live charges are made. The reconciler matches each Stripe charge against your local orders CSV by `stripe_charge_id`, classifies every delta (`AMOUNT_MISMATCH`, `CHARGE_NOT_IN_ORDERS`, `ORDER_NOT_IN_STRIPE`, `DUPLICATE_CHARGE_ID`), and writes a structured report to stdout. Runs are stateless — re-executing over the same date window produces the same report.

### Example 1: reconcile a date window

```bash
stripe-reconcile reconcile \
  --from-date 2024-01-01 \
  --to-date   2024-01-31 \
  --csv       examples/orders.csv \
  --format    json
```

Expected output (truncated to 2 discrepancy objects; exit code `1` because discrepancies were found):

```json
[
  {
    "kind": "AMOUNT_MISMATCH",
    "charge_id": "ch_1A2b3C4d5E6f",
    "order_id": "ord_1001",
    "stripe_amount_cents": 5000,
    "order_amount_cents": 4999,
    "detail": "order ord_1001 expects 4999 cents, Stripe reports 5000 cents (delta: +1)"
  },
  {
    "kind": "CHARGE_NOT_IN_ORDERS",
    "charge_id": "ch_9Z8y7X6w5V4u",
    "order_id": null,
    "stripe_amount_cents": 2500,
    "order_amount_cents": null,
    "detail": "Stripe charge 'ch_9Z8y7X6w5V4u' has no matching local order"
  }
]
```

Exit code is `0` when no discrepancies are found; `1` when at least one is detected.

### Example 2: pipe into jq for summary

```bash
stripe-reconcile reconcile \
  --csv    examples/orders.csv \
  --format json \
| jq '[.[] | .kind] | group_by(.) | map({kind: .[0], count: length})'
```

Expected output:

```json
[
  {
    "kind": "AMOUNT_MISMATCH",
    "count": 1
  },
  {
    "kind": "CHARGE_NOT_IN_ORDERS",
    "count": 3
  }
]
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `--from-date DATE` | — | Start of the reconciliation window, inclusive (ISO 8601, e.g. `2024-01-01`). Omit to include all charges from the beginning of your Stripe account. |
| `--to-date DATE` | — | End of the reconciliation window, inclusive (ISO 8601). Omit to include all charges up to now. |
| `--db PATH` | `./orders.db` | Path to the local SQLite orders database. Created if absent. |
| `--csv PATH` | — | Path to a local orders CSV file. Bulk-imported into the `--db` database before reconciling. Required columns: `order_id`, `amount_cents`, `stripe_charge_id`, `created_at`. The target database must not already contain rows (fresh DB only). |
| `--format {json,csv,table}` | `table` | Output format. `json` emits a JSON array to stdout suitable for piping; `csv` writes a comma-separated discrepancy report; `table` renders a human-readable grid. |
| `--output PATH` | — | Write the report to this file. Defaults to stdout. |
| `--enrich-subscriptions` | off | Fetch all Stripe subscriptions and append subscription ID + status to the `detail` field of `AMOUNT_MISMATCH` and `CHARGE_NOT_IN_ORDERS` discrepancies whose underlying charge carries a `subscription_id` in its metadata. |

## Architecture

```
stripe-billing-reconciler/
├── src/stripe_reconciler/
│   ├── cli.py               # Click entrypoint — parses flags, orchestrates the run, cross-source dedup
│   ├── client.py            # Stripe SDK wrapper with tenacity retry on transient errors
│   ├── fetchers/
│   │   ├── charges.py       # Cursor-paginated Charges API fetcher (with STRIPE_MOCK_CHARGES_FILE for local demos)
│   │   ├── events.py        # Cursor-paginated subscription events fetcher (invoice.payment_succeeded, charge.succeeded)
│   │   └── subscriptions.py # Cursor-paginated subscriptions fetcher (used only with --enrich-subscriptions)
│   ├── reconciler.py        # Core diff engine — joins orders against Stripe data + detect_duplicates + opt-in subscription enrichment
│   ├── classifier.py        # Pure-domain DiscrepancyClassifier (no I/O) for AMOUNT_MISMATCH + tolerance window
│   ├── store.py             # SQLite store — orders table with UNIQUE INDEX on stripe_charge_id
│   ├── models.py            # Pydantic models: StripeCharge, StripeSubscription, LocalOrder, Discrepancy, DiscrepancyKind
│   ├── formatters.py        # JSON, CSV, and table output formatters
│   └── config.py            # pydantic-settings config — SecretStr for API key, lru_cache singleton
└── tests/
    ├── unit/                # Fast, isolated tests per module
    └── integration/         # End-to-end reconcile flow against fixture data
```

**Discrepancy kinds** (`DiscrepancyKind` enum):

- `AMOUNT_MISMATCH` — both sides exist; amounts disagree beyond tolerance
- `CHARGE_NOT_IN_ORDERS` — Stripe charge with no matching local order
- `ORDER_NOT_IN_STRIPE` — local order referencing a charge Stripe did not return
- `DUPLICATE_CHARGE_ID` — the same charge ID appeared more than once in the input stream

**Key design decisions** are documented in `docs/adr/`:

- [ADR-0001](docs/adr/0001-sqlite-for-local-orders-store.md) — SQLite for the local orders store
- [ADR-0002](docs/adr/0002-cursor-based-pagination.md) — cursor-based pagination over Stripe list endpoints
- [ADR-0003](docs/adr/0003-cli-and-data-model-choices.md) — CLI framework (Click) and data-model library (Pydantic v2)
- [ADR-0004](docs/adr/0004-ai-assisted-documentation.md) — AI-assisted documentation workflow

> This repo uses AI assistance (Claude) for documentation drafting. The full
> inventory of where AI was and was not used lives in
> [docs/ai-assisted-development.md](docs/ai-assisted-development.md) — implementation
> code under `src/` is human-authored.

## Performance

End-to-end wall-time benchmarks measured with `timeit` (5 iterations, median
reported). All HTTP calls are intercepted by the `responses` library — no live
Stripe API key needed.

```bash
python bench/benchmark_pagination.py
```

Full results with machine spec: [bench/results.md](bench/results.md).

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md).

## License

[MIT](LICENSE)
