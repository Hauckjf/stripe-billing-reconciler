# Examples

Sample data and a runnable demo that exercise the reconciler end-to-end without
a live Stripe account.

## Files

| File | Description |
|------|-------------|
| `sample_orders.csv` | 20-row orders table: 17 clean matches, 2 amount mismatches, 1 orphan order |
| `mock_charges.json` | 22 Stripe-style charges: 17 clean, 2 mismatches, 2 orphan charges |
| `run_local_demo.sh` | Bash script that wires the two files together and runs the CLI |
| `orders.csv` | Minimal 4-row CSV from the project README quick-start |

## Discrepancy map

| CSV row(s) | Charge in JSON | Order ¢ / Stripe ¢ | Expected result |
|------------|----------------|--------------------|-----------------|
| `ord_2001`–`ord_2017` | `ch_demo_001`–`ch_demo_017` | match | no discrepancy |
| `ord_2018` | `ch_demo_018` | 4 999 / 5 000 | `AMOUNT_MISMATCH` |
| `ord_2019` | `ch_demo_019` | 12 900 / 13 000 | `AMOUNT_MISMATCH` |
| `ord_2020` | `ch_ghost_999` *(absent from JSON)* | 7 500 / — | `ORDER_NOT_IN_STRIPE` |
| — | `ch_demo_020` | — / 2 500 | `CHARGE_NOT_IN_ORDERS` |
| — | `ch_demo_021` | — / 1 500 | `CHARGE_NOT_IN_ORDERS` |

Total: **5 discrepancies**. The CLI exits with code **1**.

## Prerequisites

- Python 3.11 or later
- The package installed in your active virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
```

No Stripe account or live API key is required. `run_local_demo.sh` sets two
environment variables before invoking the CLI:

- `STRIPE_API_KEY=sk_test_fake_key_local_demo_only` — satisfies the settings
  validator without touching the network.
- `STRIPE_MOCK_CHARGES_FILE=examples/mock_charges.json` — tells the charges
  fetcher to read local JSON instead of calling the Stripe API. Date range
  filters (`--from-date` / `--to-date`) are bypassed in mock mode; all charges
  in the file are returned unconditionally.

## Running the demo

```bash
bash examples/run_local_demo.sh
```

Sample table output:

```
 Kind                  Charge ID      Order ID   Stripe Amount (¢)  Order Amount (¢)  Detail
 AMOUNT_MISMATCH       ch_demo_018    ord_2018   5000               4999              order ord_2018 expects 4999 cents, Stripe reports 5000 cents (delta: +1)
 AMOUNT_MISMATCH       ch_demo_019    ord_2019   13000              12900             order ord_2019 expects 12900 cents, Stripe reports 13000 cents (delta: +100)
 ORDER_NOT_IN_STRIPE   ch_ghost_999   ord_2020                      7500              order 'ord_2020' references charge 'ch_ghost_999' not returned by Stripe
 CHARGE_NOT_IN_ORDERS  ch_demo_020               2500                                 Stripe charge 'ch_demo_020' has no matching local order
 CHARGE_NOT_IN_ORDERS  ch_demo_021               1500                                 Stripe charge 'ch_demo_021' has no matching local order
```

Sample JSON output (abbreviated):

```json
[
  {
    "kind": "AMOUNT_MISMATCH",
    "charge_id": "ch_demo_018",
    "order_id": "ord_2018",
    "stripe_amount_cents": 5000,
    "order_amount_cents": 4999,
    "detail": "order ord_2018 expects 4999 cents, Stripe reports 5000 cents (delta: +1)"
  },
  {
    "kind": "ORDER_NOT_IN_STRIPE",
    "charge_id": "ch_ghost_999",
    "order_id": "ord_2020",
    "stripe_amount_cents": null,
    "order_amount_cents": 7500,
    "detail": "order 'ord_2020' references charge 'ch_ghost_999' not returned by Stripe"
  },
  {
    "kind": "CHARGE_NOT_IN_ORDERS",
    "charge_id": "ch_demo_020",
    "order_id": null,
    "stripe_amount_cents": 2500,
    "order_amount_cents": null,
    "detail": "Stripe charge 'ch_demo_020' has no matching local order"
  }
]
```

## Filtering with jq

Isolate AMOUNT_MISMATCH discrepancies:

```bash
STRIPE_API_KEY=sk_test_fake_key_local_demo_only \
STRIPE_MOCK_CHARGES_FILE=examples/mock_charges.json \
stripe-reconcile reconcile \
  --csv examples/sample_orders.csv \
  --format json \
| jq '[.[] | select(.kind == "AMOUNT_MISMATCH") | {charge_id, order_id, stripe_amount_cents, order_amount_cents}]'
```

Expected output:

```json
[
  {
    "charge_id": "ch_demo_018",
    "order_id": "ord_2018",
    "stripe_amount_cents": 5000,
    "order_amount_cents": 4999
  },
  {
    "charge_id": "ch_demo_019",
    "order_id": "ord_2019",
    "stripe_amount_cents": 13000,
    "order_amount_cents": 12900
  }
]
```
