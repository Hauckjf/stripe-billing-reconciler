# Stripe Billing Reconciler

![CI](https://github.com/Hauckjf/stripe-billing-reconciler/actions/workflows/ci.yml/badge.svg) ![License](https://img.shields.io/github/license/Hauckjf/stripe-billing-reconciler?color=blue) ![Last commit](https://img.shields.io/github/last-commit/Hauckjf/stripe-billing-reconciler)

> Reconcile Stripe charges and subscriptions against your internal orders table — cursor-paginated, idempotent, rate-limit-aware, and auditable.

CLI tool written in Python — chosen for scripting ergonomics and Stripe SDK maturity — that fetches Stripe charge and subscription events via cursor-based pagination, cross-references them against a local orders table (columns: order_id TEXT, amount_cents INTEGER, stripe_charge_id TEXT, created_at TIMESTAMP), and outputs a structured discrepancy report.

## Table of contents

- [About](#about)
- [Tech](#tech)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

## About

CLI tool written in Python — chosen for scripting ergonomics and Stripe SDK maturity — that fetches Stripe charge and subscription events via cursor-based pagination, cross-references them against a local orders table (columns: order_id TEXT, amount_cents INTEGER, stripe_charge_id TEXT, created_at TIMESTAMP), and outputs a structured discrepancy report.

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

Any [Stripe test-mode key](https://dashboard.stripe.com/test/apikeys) works; no live charges are made.

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
| `--csv PATH` | — | Path to the local orders CSV file. Required columns: `order_id`, `amount_cents`, `stripe_charge_id`, `created_at`. |
| `--format {json,table}` | `table` | Output format. `json` emits a JSON array to stdout suitable for piping; `table` renders a human-readable grid. |
| `--tolerance-cents INT` | `0` | Ignore amount deltas within this many cents. Useful for rounding differences between systems. |
| `--resume` | off | Resume from the last saved cursor checkpoint stored in `reconciler.db`. Use after an interrupted run to avoid re-fetching already-processed events. |

## Architecture

```
stripe-billing-reconciler/
├── src/stripe_reconciler/
│   ├── cli.py               # Click entrypoint — parses flags, orchestrates the run
│   ├── client.py            # Stripe SDK wrapper with token-bucket rate limiter
│   ├── fetchers/
│   │   ├── charges.py       # Cursor-paginated charge fetcher
│   │   ├── events.py        # Event stream fetcher (subscription change events)
│   │   └── subscriptions.py # Subscription fetcher
│   ├── reconciler.py        # Core diff engine — joins orders against Stripe data
│   ├── classifier.py        # Labels discrepancies: AMOUNT_MISMATCH, CHARGE_NOT_IN_ORDERS, ORDER_NOT_IN_STRIPE
│   ├── store.py             # SQLite store — orders table + checkpoint table
│   ├── models.py            # Typed models: Charge, Order, Discrepancy
│   ├── formatters.py        # JSON and table output formatters
│   └── config.py            # Config loading (env vars + CLI flags)
└── tests/
    ├── unit/                # Fast, isolated tests per module
    └── integration/         # End-to-end reconcile flow against fixture data
```

**Key design decisions** are documented in `docs/adr/`:

- [ADR-0001](docs/adr/0001-sqlite-for-local-orders-store.md) — SQLite for local orders store
- [ADR-0002](docs/adr/0002-cursor-based-pagination.md) — cursor-based pagination
- [ADR-0003](docs/adr/0003-cli-and-data-model-choices.md) — CLI and data model choices

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md).

## License

[MIT](LICENSE)
