"""Edge-case tests: zero amounts, inverted date windows, CRLF CSV, and empty formatter output."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from stripe_reconciler.fetchers.charges import fetch_all_charges
from stripe_reconciler.formatters import to_csv, to_json, to_table
from stripe_reconciler.models import DiscrepancyKind, StripeCharge
from stripe_reconciler.reconciler import reconcile
from stripe_reconciler.store import OrdersStore


# ── shared helpers ────────────────────────────────────────────────────────────


def _make_charge(
    charge_id: str = "ch_test",
    amount: int = 1_000,
    currency: str = "usd",
    status: str = "succeeded",
    created: datetime | None = None,
) -> StripeCharge:
    return StripeCharge(
        id=charge_id,
        amount=amount,
        currency=currency,
        created=created or datetime(2024, 3, 1, tzinfo=timezone.utc),
        status=status,
    )


def _store_with_order(
    order_id: str,
    amount_cents: int,
    stripe_charge_id: str,
) -> OrdersStore:
    """Return an in-memory OrdersStore pre-populated with a single order."""
    store = OrdersStore(":memory:")
    store.conn.execute(
        "INSERT INTO orders (order_id, amount_cents, stripe_charge_id, created_at)"
        " VALUES (?, ?, ?, ?)",
        (
            order_id,
            amount_cents,
            stripe_charge_id,
            datetime(2024, 3, 1, tzinfo=timezone.utc).isoformat(),
        ),
    )
    store.conn.commit()
    return store


def _page(data: list[MagicMock], *, has_more: bool = False) -> MagicMock:
    page: MagicMock = MagicMock()
    page.data = data
    page.has_more = has_more
    return page


# ── Case 1: zero-amount match ─────────────────────────────────────────────────


class TestZeroAmountMatch:
    def test_zero_amount_charge_with_matching_zero_order_no_discrepancy(self) -> None:
        """Charge amount=0 paired with order amount_cents=0 must reconcile cleanly."""
        charge = _make_charge(charge_id="ch_zero", amount=0)
        store = _store_with_order("ord_zero", amount_cents=0, stripe_charge_id="ch_zero")

        result = reconcile([charge], store)

        assert result == []

    def test_zero_amount_charge_against_nonzero_order_is_flagged(self) -> None:
        """Zero-amount charge vs. non-zero order must produce an AMOUNT_MISMATCH."""
        charge = _make_charge(charge_id="ch_zero", amount=0)
        store = _store_with_order("ord_pos", amount_cents=500, stripe_charge_id="ch_zero")

        result = reconcile([charge], store)

        assert len(result) == 1
        assert result[0].kind == DiscrepancyKind.AMOUNT_MISMATCH
        assert result[0].stripe_amount_cents == 0
        assert result[0].order_amount_cents == 500


# ── Case 2: inverted date window yields no items ──────────────────────────────


class TestInvertedDateWindow:
    def test_inverted_window_fetcher_yields_nothing(self) -> None:
        """When gte is after lte the API returns empty results; fetcher must not crash.

        Stripe returns an empty page for invalid windows; the fetcher must not
        raise and must yield zero items so callers handle the no-op gracefully.
        """
        client: MagicMock = MagicMock()
        client.list_charges.return_value = _page([], has_more=False)

        now = datetime(2024, 3, 15, tzinfo=timezone.utc)
        past = now - timedelta(days=7)

        # Inverted: created_gte is after created_lte
        result = list(
            fetch_all_charges(
                cast(object, client),  # type: ignore[arg-type]
                created_gte=now,
                created_lte=past,
                page_size=100,
            )
        )

        assert result == []
        client.list_charges.assert_called_once()

    def test_inverted_window_epoch_ints_still_forwarded_to_api(self) -> None:
        """Even with an inverted range the timestamps are forwarded; Stripe decides."""
        client: MagicMock = MagicMock()
        client.list_charges.return_value = _page([], has_more=False)

        gte = datetime(2024, 3, 15, tzinfo=timezone.utc)
        lte = datetime(2024, 3, 1, tzinfo=timezone.utc)  # earlier than gte

        list(
            fetch_all_charges(
                cast(object, client),  # type: ignore[arg-type]
                created_gte=gte,
                created_lte=lte,
                page_size=10,
            )
        )

        client.list_charges.assert_called_once_with(
            starting_after=None,
            limit=10,
            created_gte=int(gte.timestamp()),
            created_lte=int(lte.timestamp()),
        )


# ── Case 3: to_json([]) must return "[]" not "null" ───────────────────────────


class TestToJsonEmpty:
    def test_empty_list_serialises_to_empty_json_array(self) -> None:
        """to_json([]) must return the literal string '[]', never 'null'."""
        result = to_json([])

        assert result == "[]"

    def test_empty_result_is_valid_parseable_json(self) -> None:
        """The string returned for an empty list must round-trip through json.loads."""
        result = to_json([])
        parsed = json.loads(result)

        assert parsed == []
        assert isinstance(parsed, list)


# ── Case 4: to_csv([]) must return only the header line ──────────────────────


class TestToCsvEmpty:
    def test_empty_list_produces_header_only(self) -> None:
        """to_csv([]) must emit exactly one line — the column header."""
        result = to_csv([])
        lines = result.splitlines()

        assert len(lines) == 1
        assert lines[0] == "kind,charge_id,order_id,stripe_amount_cents,order_amount_cents,detail"

    def test_empty_csv_ends_with_newline(self) -> None:
        """CSV output must end with a newline so it's safe to concatenate or pipe."""
        result = to_csv([])

        assert result.endswith("\n")


# ── Case 5: to_table([]) must render headers without data rows ────────────────


class TestToTableEmpty:
    def test_empty_table_contains_column_headers(self) -> None:
        """to_table([]) must include column header text (no data rows required)."""
        result = to_table([])

        assert "Kind" in result
        assert "Charge ID" in result
        assert "Order ID" in result

    def test_empty_table_contains_no_charge_or_order_data(self) -> None:
        """When the discrepancy list is empty, no charge IDs or amounts appear."""
        result = to_table([])

        # No real identifiers from actual discrepancies should appear
        assert "ch_" not in result
        assert "ord_" not in result


# ── Case 6: CRLF CSV loading ──────────────────────────────────────────────────


class TestCrlfCsv:
    def test_crlf_csv_loads_all_rows(self, tmp_path: Path) -> None:
        """Windows CRLF line endings must not corrupt row count or field values."""
        csv_bytes = (
            b"order_id,amount_cents,stripe_charge_id,created_at\r\n"
            b"ord_w1,1000,ch_w1,2024-03-01T12:00:00+00:00\r\n"
            b"ord_w2,2500,ch_w2,2024-03-02T12:00:00+00:00\r\n"
        )
        csv_file = tmp_path / "crlf_orders.csv"
        csv_file.write_bytes(csv_bytes)

        store = OrdersStore(":memory:")
        store.load_from_csv(csv_file)
        orders = store.get_all_orders()

        assert len(orders) == 2
        ids = {o.order_id for o in orders}
        assert "ord_w1" in ids
        assert "ord_w2" in ids

    def test_crlf_csv_preserves_amount_cents_exactly(self, tmp_path: Path) -> None:
        """CRLF stripping must not leave trailing whitespace that corrupts int parsing."""
        csv_bytes = (
            b"order_id,amount_cents,stripe_charge_id,created_at\r\n"
            b"ord_w3,9999,ch_w3,2024-03-03T12:00:00+00:00\r\n"
        )
        csv_file = tmp_path / "crlf_single.csv"
        csv_file.write_bytes(csv_bytes)

        store = OrdersStore(":memory:")
        store.load_from_csv(csv_file)
        order = store.get_order_by_charge_id("ch_w3")

        assert order is not None
        assert order.order_id == "ord_w3"
        assert order.amount_cents == 9_999


# ── Currency variants ─────────────────────────────────────────────────────────


class TestCurrencyVariants:
    def test_eur_charge_matching_eur_order_no_discrepancy(self) -> None:
        """Currency is informational; reconciler compares amounts only."""
        charge = _make_charge(charge_id="ch_eur", amount=5_000, currency="eur")
        store = _store_with_order("ord_eur", amount_cents=5_000, stripe_charge_id="ch_eur")

        result = reconcile([charge], store)

        assert result == []

    def test_gbp_charge_with_amount_mismatch_is_classified_correctly(self) -> None:
        """Currency field does not affect discrepancy classification."""
        charge = _make_charge(charge_id="ch_gbp", amount=3_000, currency="gbp")
        store = _store_with_order("ord_gbp", amount_cents=2_000, stripe_charge_id="ch_gbp")

        result = reconcile([charge], store)

        assert len(result) == 1
        assert result[0].kind == DiscrepancyKind.AMOUNT_MISMATCH
        assert result[0].stripe_amount_cents == 3_000
        assert result[0].order_amount_cents == 2_000
