"""Behavioural tests for the reconciler engine."""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stripe_reconciler.models import DiscrepancyKind, StripeCharge
from stripe_reconciler.reconciler import reconcile
from stripe_reconciler.store import OrdersStore

_NOW = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
_CREATED_AT_ISO = "2024-03-01T12:00:00+00:00"


def _charge(charge_id: str, amount: int = 1000) -> StripeCharge:
    return StripeCharge(
        id=charge_id,
        amount=amount,
        currency="usd",
        created=_NOW,
        status="succeeded",
    )


@pytest.fixture()
def store(tmp_path: Path) -> Generator[OrdersStore, None, None]:
    s = OrdersStore(tmp_path / "reconciler_test.db")
    yield s
    s.close()


def _seed_store(
    store: OrdersStore,
    tmp_path: Path,
    rows: list[tuple[str, int, str]],
) -> None:
    """Insert rows of (order_id, amount_cents, stripe_charge_id) into the store via CSV."""
    csv_path = tmp_path / "seed.csv"
    lines = ["order_id,amount_cents,stripe_charge_id,created_at"]
    for order_id, amount_cents, charge_id in rows:
        lines.append(f"{order_id},{amount_cents},{charge_id},{_CREATED_AT_ISO}")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    store.load_from_csv(csv_path)


class TestCleanRun:
    def test_empty_charges_and_empty_store_returns_empty(
        self, store: OrdersStore
    ) -> None:
        assert reconcile([], store) == []

    def test_all_matched_exact_amounts_no_discrepancies(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(
            store,
            tmp_path,
            [("ord_001", 1000, "ch_001"), ("ord_002", 2000, "ch_002")],
        )
        charges = [_charge("ch_001", 1000), _charge("ch_002", 2000)]
        assert reconcile(charges, store) == []

    def test_returns_list_not_generator(self, store: OrdersStore) -> None:
        result = reconcile(iter([_charge("ch_x")]), store)
        assert isinstance(result, list)

    def test_accepts_one_shot_generator(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        """reconcile must not re-iterate charges — it may be a one-shot generator."""
        _seed_store(store, tmp_path, [("ord_001", 1000, "ch_001")])

        def one_shot() -> Generator[StripeCharge, None, None]:
            yield _charge("ch_001", 1000)
            yield _charge("ch_002", 2000)

        result = reconcile(one_shot(), store)
        assert len(result) == 1
        assert result[0].kind == DiscrepancyKind.CHARGE_NOT_IN_ORDERS
        assert result[0].charge_id == "ch_002"


class TestAmountMismatch:
    def test_mismatch_detected_correct_fields(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(store, tmp_path, [("ord_001", 900, "ch_001")])
        result = reconcile([_charge("ch_001", 1000)], store)

        assert len(result) == 1
        d = result[0]
        assert d.kind == DiscrepancyKind.AMOUNT_MISMATCH
        assert d.charge_id == "ch_001"
        assert d.order_id == "ord_001"
        assert d.stripe_amount_cents == 1000
        assert d.order_amount_cents == 900

    def test_exact_match_produces_no_discrepancy(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(store, tmp_path, [("ord_001", 1500, "ch_001")])
        assert reconcile([_charge("ch_001", 1500)], store) == []

    def test_detail_contains_both_amounts(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(store, tmp_path, [("ord_001", 800, "ch_001")])
        result = reconcile([_charge("ch_001", 1000)], store)
        assert "1000" in result[0].detail
        assert "800" in result[0].detail


class TestChargeNotInOrders:
    def test_orphan_charge_all_fields(
        self, store: OrdersStore
    ) -> None:
        result = reconcile([_charge("ch_orphan", 5000)], store)

        assert len(result) == 1
        d = result[0]
        assert d.kind == DiscrepancyKind.CHARGE_NOT_IN_ORDERS
        assert d.charge_id == "ch_orphan"
        assert d.order_id is None
        assert d.stripe_amount_cents == 5000
        assert d.order_amount_cents is None

    def test_multiple_orphan_charges_all_reported(
        self, store: OrdersStore
    ) -> None:
        charges = [_charge("ch_a"), _charge("ch_b"), _charge("ch_c")]
        result = reconcile(charges, store)
        assert len(result) == 3
        assert all(d.kind == DiscrepancyKind.CHARGE_NOT_IN_ORDERS for d in result)

    def test_empty_store_all_charges_are_orphans(
        self, store: OrdersStore
    ) -> None:
        result = reconcile([_charge("ch_001"), _charge("ch_002")], store)
        ids = {d.charge_id for d in result}
        assert ids == {"ch_001", "ch_002"}


class TestOrderNotInStripe:
    def test_orphan_order_all_fields(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(store, tmp_path, [("ord_001", 1000, "ch_missing")])
        result = reconcile([], store)

        assert len(result) == 1
        d = result[0]
        assert d.kind == DiscrepancyKind.ORDER_NOT_IN_STRIPE
        assert d.charge_id == "ch_missing"
        assert d.order_id == "ord_001"
        assert d.order_amount_cents == 1000
        assert d.stripe_amount_cents is None

    def test_detail_references_missing_charge_id(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(store, tmp_path, [("ord_001", 500, "ch_gone")])
        result = reconcile([], store)
        assert "ch_gone" in result[0].detail

    def test_charges_with_no_store_match_does_not_emit_order_not_in_stripe(
        self, store: OrdersStore
    ) -> None:
        """Charges with no orders produce CHARGE_NOT_IN_ORDERS, not ORDER_NOT_IN_STRIPE."""
        result = reconcile([_charge("ch_001")], store)
        assert len(result) == 1
        assert result[0].kind == DiscrepancyKind.CHARGE_NOT_IN_ORDERS


class TestCombinedScenario:
    def test_one_mismatch_one_orphan_charge_returns_exactly_two_discrepancies(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        # ch_clean  : Stripe 1000 == order 1000  → no discrepancy
        # ch_mismatch: Stripe 2000 != order 1500 → AMOUNT_MISMATCH
        # ch_orphan : Stripe charge, no order    → CHARGE_NOT_IN_ORDERS
        _seed_store(
            store,
            tmp_path,
            [
                ("ord_clean", 1000, "ch_clean"),
                ("ord_mismatch", 1500, "ch_mismatch"),
            ],
        )
        charges = [
            _charge("ch_clean", 1000),
            _charge("ch_mismatch", 2000),
            _charge("ch_orphan", 3000),
        ]

        result = reconcile(charges, store)

        assert len(result) == 2
        kinds = {d.kind for d in result}
        assert kinds == {
            DiscrepancyKind.AMOUNT_MISMATCH,
            DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
        }

    def test_all_three_discrepancy_kinds_in_single_run(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        # ord_ghost  → ch_ghost (not in charges)         → ORDER_NOT_IN_STRIPE
        # ch_mismatch ↔ ord_mismatch (amounts differ)    → AMOUNT_MISMATCH
        # ch_orphan has no order                         → CHARGE_NOT_IN_ORDERS
        _seed_store(
            store,
            tmp_path,
            [
                ("ord_ghost", 999, "ch_ghost"),
                ("ord_mismatch", 500, "ch_mismatch"),
            ],
        )
        charges = [_charge("ch_mismatch", 600), _charge("ch_orphan", 800)]

        result = reconcile(charges, store)

        assert len(result) == 3
        kinds = {d.kind for d in result}
        assert kinds == {
            DiscrepancyKind.ORDER_NOT_IN_STRIPE,
            DiscrepancyKind.AMOUNT_MISMATCH,
            DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
        }

    def test_mismatch_discrepancy_has_correct_charge_and_order_ids(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(store, tmp_path, [("ord_abc", 750, "ch_xyz")])
        result = reconcile([_charge("ch_xyz", 1000)], store)

        assert len(result) == 1
        d = result[0]
        assert d.charge_id == "ch_xyz"
        assert d.order_id == "ord_abc"
