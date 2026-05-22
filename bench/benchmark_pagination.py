#!/usr/bin/env python3
"""Performance benchmarks for stripe-billing-reconciler.

Three scenarios, 5 iterations each (median wall time reported):

  S1   Paginate 1 000 charges across 10 pages of 100 via mocked Stripe HTTP.
  S2   Reconcile 1 000 charges against 1 000 orders — all matching, best-case.
  S3a  Render 1 000 discrepancies to JSON.
  S3b  Render 1 000 discrepancies to a Rich table string.

Run::

    python bench/benchmark_pagination.py

No live Stripe API key is needed; all HTTP calls are intercepted by the
``responses`` library (a dev dependency — run ``pip install -e '.[dev]'`` first).
"""

from __future__ import annotations

import atexit
import csv
import json
import shutil
import statistics
import sys
import tempfile
import timeit
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import responses

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from stripe_reconciler.client import StripeClient  # noqa: E402
from stripe_reconciler.fetchers.charges import fetch_all_charges  # noqa: E402
from stripe_reconciler.formatters import to_json, to_table  # noqa: E402
from stripe_reconciler.models import Discrepancy, DiscrepancyKind, StripeCharge  # noqa: E402
from stripe_reconciler.reconciler import reconcile  # noqa: E402
from stripe_reconciler.store import OrdersStore  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
N = 1_000        # charges, orders, and discrepancies per scenario
PAGE_SIZE = 100  # 10 pages to cover N charges
N_PAGES = N // PAGE_SIZE
ITERATIONS = 5
_EPOCH_BASE = 1_700_000_000   # 2023-11-15 00:00:00 UTC
_FAKE_KEY = "sk_test_bench_00000000000000000000"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="sbr_bench_"))
atexit.register(shutil.rmtree, _TMP_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------
# Fixture builders — run once at module load, NOT part of the timed loops
# ---------------------------------------------------------------------------

def _make_raw_charge(i: int) -> dict[str, Any]:
    return {
        "id": f"ch_{i:04d}",
        "object": "charge",
        "amount": 1_000 + i,
        "currency": "usd",
        "created": _EPOCH_BASE + i,
        "status": "succeeded",
        "metadata": {},
        "livemode": False,
        "paid": True,
        "refunded": False,
    }


def _build_stripe_pages() -> tuple[list[dict[str, Any]], int]:
    """Pre-build 10 pages of 100 charges each as Stripe list-response dicts.

    Returns (pages, total_raw_bytes) so the caller can compute throughput
    against the actual JSON payload that would travel over the wire.
    """
    all_raw = [_make_raw_charge(i) for i in range(N)]
    pages: list[dict[str, Any]] = []
    for p in range(N_PAGES):
        chunk = all_raw[p * PAGE_SIZE : (p + 1) * PAGE_SIZE]
        pages.append(
            {
                "object": "list",
                "url": "/v1/charges",
                "has_more": p < N_PAGES - 1,
                "data": chunk,
            }
        )
    total_bytes = sum(len(json.dumps(pg).encode()) for pg in pages)
    return pages, total_bytes


def _build_matching_charges() -> list[StripeCharge]:
    return [
        StripeCharge(
            id=f"ch_{i:04d}",
            amount=1_000 + i,
            currency="usd",
            created=datetime.fromtimestamp(_EPOCH_BASE + i, tz=timezone.utc),
            status="succeeded",
        )
        for i in range(N)
    ]


def _build_matching_store() -> OrdersStore:
    """Write a CSV with N matching orders and load it into an SQLite store."""
    csv_path = _TMP_DIR / "orders.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["order_id", "amount_cents", "stripe_charge_id", "created_at"])
        for i in range(N):
            writer.writerow(
                [f"ord_{i:04d}", 1_000 + i, f"ch_{i:04d}", "2024-01-01T00:00:00"]
            )
    store = OrdersStore(_TMP_DIR / "bench.db")
    store.load_from_csv(csv_path)
    return store


def _build_discrepancies() -> list[Discrepancy]:
    return [
        Discrepancy(
            kind=DiscrepancyKind.AMOUNT_MISMATCH,
            charge_id=f"ch_{i:04d}",
            order_id=f"ord_{i:04d}",
            stripe_amount_cents=1_000 + i,
            order_amount_cents=900 + i,
            detail=(
                f"order ord_{i:04d} expects {900 + i} cents,"
                f" Stripe reports {1_000 + i} cents (delta: +100)"
            ),
        )
        for i in range(N)
    ]


# Module-level fixtures (build cost is not counted in benchmark timing)
STRIPE_PAGES, _S1_BYTES = _build_stripe_pages()
CHARGES = _build_matching_charges()
STORE = _build_matching_store()
DISCREPANCIES = _build_discrepancies()


# ---------------------------------------------------------------------------
# Benchmark functions — one call = one timed iteration
# ---------------------------------------------------------------------------

def s1_paginate() -> int:
    """Fetch all 1 000 charges across 10 mocked HTTP pages; return count.

    Uses ``responses.RequestsMock`` so the Stripe SDK's HTTP layer is fully
    exercised (JSON encode/decode, SDK object construction, cursor extraction)
    without hitting the network.
    """
    page_idx: list[int] = [0]

    def _cb(req: Any) -> tuple[int, dict[str, str], str]:
        idx = page_idx[0]
        page_idx[0] += 1
        return (200, {"Content-Type": "application/json"}, json.dumps(STRIPE_PAGES[idx]))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET,
            "https://api.stripe.com/v1/charges",
            callback=_cb,
        )
        client = StripeClient(api_key=_FAKE_KEY)
        return sum(1 for _ in fetch_all_charges(client, None, None, PAGE_SIZE))


def s2_reconcile() -> int:
    """Reconcile 1 000 pre-built charges against 1 000 matching orders.

    All charges have a corresponding order with the same amount — zero
    discrepancies expected. This is the best-case O(N) hash-join path.
    """
    return len(reconcile(CHARGES, STORE))


def s3a_json() -> int:
    """Serialise 1 000 discrepancies to pretty-printed JSON; return byte count."""
    return len(to_json(DISCREPANCIES).encode())


def s3b_table() -> int:
    """Render 1 000 discrepancies as a Rich table string; return byte count."""
    return len(to_table(DISCREPANCIES).encode())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _mbps(nbytes: int, median_s: float) -> str:
    if median_s <= 0:
        return "        —"
    return f"{nbytes / (1_024 ** 2) / median_s:7.1f} MB/s"


def main() -> None:
    SEP = "=" * 70
    print(f"\n{SEP}")
    print("  stripe-billing-reconciler — performance benchmarks")
    print(f"  {ITERATIONS} iterations each  ·  median wall time")
    print(f"{SEP}\n")

    # One warm-up call per scenario to avoid first-run import/module caching effects
    print("  Warming up…")
    s1_paginate()
    s2_reconcile()
    s3a_json()
    s3b_table()

    print("  Running benchmarks…\n")

    t1 = timeit.repeat(s1_paginate, number=1, repeat=ITERATIONS)
    t2 = timeit.repeat(s2_reconcile, number=1, repeat=ITERATIONS)
    t3a = timeit.repeat(s3a_json, number=1, repeat=ITERATIONS)
    t3b = timeit.repeat(s3b_table, number=1, repeat=ITERATIONS)

    med1 = statistics.median(t1)
    med2 = statistics.median(t2)
    med3a = statistics.median(t3a)
    med3b = statistics.median(t3b)

    json_bytes = len(to_json(DISCREPANCIES).encode())
    table_bytes = len(to_table(DISCREPANCIES).encode())

    DIV = "-" * 70
    print(f"  {DIV}")
    print(f"  {'Scenario':<52} {'Median':>8}   {'Throughput':>9}")
    print(f"  {DIV}")

    rows: list[tuple[str, str, str]] = [
        (
            f"S1   Paginate {N:,} charges (10 pages \u00d7 100, mocked HTTP)",
            f"{med1 * 1_000:6.1f} ms",
            _mbps(_S1_BYTES, med1),
        ),
        (
            f"S2   Reconcile {N:,} charges \u00d7 {N:,} orders (all match)",
            f"{med2 * 1_000:6.1f} ms",
            "        —",
        ),
        (
            f"S3a  Render {N:,} discrepancies \u2192 JSON  ({json_bytes:,} B)",
            f"{med3a * 1_000:6.1f} ms",
            _mbps(json_bytes, med3a),
        ),
        (
            f"S3b  Render {N:,} discrepancies \u2192 Rich table  ({table_bytes:,} B)",
            f"{med3b * 1_000:6.1f} ms",
            _mbps(table_bytes, med3b),
        ),
    ]

    for label, med, tp in rows:
        print(f"  {label:<52} {med:>8}   {tp}")

    print(f"  {DIV}\n")
    print("  Full results + machine spec \u2192 bench/results.md\n")


if __name__ == "__main__":
    main()
