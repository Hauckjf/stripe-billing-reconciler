"""Behavioural tests for the reconciler engine."""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stripe_reconciler.models import DiscrepancyKind, LocalOrder, StripeCharge
from stripe_reconciler.reconciler import build_detail, detect_duplicates, reconcile
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


def _order(order_id: str, amount_cents: int, stripe_charge_id: str) -> LocalOrder:
    return LocalOrder(
        order_id=order_id,
        amount_cents=amount_cents,
        stripe_charge_id=stripe_charge_id,
        created_at=_NOW,
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

    def test_three_charges_three_orders_all_matched_returns_empty(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(
            store,
            tmp_path,
            [
                ("ord_001", 1000, "ch_001"),
                ("ord_002", 2500, "ch_002"),
                ("ord_003", 750, "ch_003"),
            ],
        )
        charges = [
            _charge("ch_001", 1000),
            _charge("ch_002", 2500),
            _charge("ch_003", 750),
        ]
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

    def test_all_four_discrepancy_kinds_exactly_four_total(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        # ch_dup appears twice              → DUPLICATE_CHARGE_ID  (1 discrepancy)
        # ch_dup has matching order (same amount) → no extra discrepancy
        # ch_mismatch (600) vs ord (500)   → AMOUNT_MISMATCH      (1 discrepancy)
        # ch_orphan has no local order     → CHARGE_NOT_IN_ORDERS (1 discrepancy)
        # ch_ghost order, no Stripe charge → ORDER_NOT_IN_STRIPE   (1 discrepancy)
        _seed_store(
            store,
            tmp_path,
            [
                ("ord_dup", 1000, "ch_dup"),
                ("ord_mismatch", 500, "ch_mismatch"),
                ("ord_ghost", 999, "ch_ghost"),
            ],
        )
        charges = [
            _charge("ch_dup", 1000),
            _charge("ch_dup", 1000),
            _charge("ch_mismatch", 600),
            _charge("ch_orphan", 800),
        ]

        result = reconcile(charges, store)

        assert len(result) == 4
        kinds = {d.kind for d in result}
        assert kinds == {
            DiscrepancyKind.DUPLICATE_CHARGE_ID,
            DiscrepancyKind.AMOUNT_MISMATCH,
            DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
            DiscrepancyKind.ORDER_NOT_IN_STRIPE,
        }


class TestBuildDetail:
    def test_amount_mismatch_contains_order_id_and_both_amounts(self) -> None:
        charge = _charge("ch_001", 1450)
        order = _order("ORD-123", 1500, "ch_001")
        detail = build_detail(DiscrepancyKind.AMOUNT_MISMATCH, charge, order)
        assert "ORD-123" in detail
        assert "1500" in detail
        assert "1450" in detail

    def test_amount_mismatch_delta_is_stripe_minus_order(self) -> None:
        charge = _charge("ch_001", 1450)
        order = _order("ORD-123", 1500, "ch_001")
        detail = build_detail(DiscrepancyKind.AMOUNT_MISMATCH, charge, order)
        assert "-50" in detail

    def test_amount_mismatch_positive_delta_shown_with_sign(self) -> None:
        charge = _charge("ch_001", 2000)
        order = _order("ORD-456", 1500, "ch_001")
        detail = build_detail(DiscrepancyKind.AMOUNT_MISMATCH, charge, order)
        assert "+500" in detail

    def test_charge_not_in_orders_contains_charge_id(self) -> None:
        charge = _charge("ch_orphan", 999)
        detail = build_detail(DiscrepancyKind.CHARGE_NOT_IN_ORDERS, charge, None)
        assert "ch_orphan" in detail

    def test_order_not_in_stripe_contains_order_and_charge_refs(self) -> None:
        order = _order("ord_ghost", 500, "ch_missing")
        detail = build_detail(DiscrepancyKind.ORDER_NOT_IN_STRIPE, None, order)
        assert "ord_ghost" in detail
        assert "ch_missing" in detail

    def test_duplicate_charge_id_contains_charge_id(self) -> None:
        charge = _charge("ch_dup", 100)
        detail = build_detail(DiscrepancyKind.DUPLICATE_CHARGE_ID, charge, None)
        assert "ch_dup" in detail

    def test_all_kinds_return_non_empty_string(self) -> None:
        charge = _charge("ch_x", 500)
        order = _order("ord_x", 500, "ch_x")
        cases = [
            (DiscrepancyKind.AMOUNT_MISMATCH, charge, order),
            (DiscrepancyKind.CHARGE_NOT_IN_ORDERS, charge, None),
            (DiscrepancyKind.ORDER_NOT_IN_STRIPE, None, order),
            (DiscrepancyKind.DUPLICATE_CHARGE_ID, charge, None),
        ]
        for kind, c, o in cases:
            assert build_detail(kind, c, o), f"detail must be non-empty for {kind}"


class TestDuplicateDetection:
    def test_no_duplicates_returns_empty(self) -> None:
        charges = [_charge("ch_001"), _charge("ch_002"), _charge("ch_003")]
        assert detect_duplicates(charges) == []

    def test_two_charges_same_id_yields_one_discrepancy(self) -> None:
        charges = [_charge("ch_dup", 1000), _charge("ch_dup", 1000)]
        result = detect_duplicates(charges)
        assert len(result) == 1
        d = result[0]
        assert d.kind == DiscrepancyKind.DUPLICATE_CHARGE_ID
        assert d.charge_id == "ch_dup"
        assert d.order_id is None
        assert d.detail != ""

    def test_three_charges_same_id_still_yields_one_discrepancy(self) -> None:
        charges = [_charge("ch_dup"), _charge("ch_dup"), _charge("ch_dup")]
        result = detect_duplicates(charges)
        assert len(result) == 1
        assert result[0].kind == DiscrepancyKind.DUPLICATE_CHARGE_ID

    def test_two_separate_duplicate_groups_yield_two_discrepancies(self) -> None:
        charges = [
            _charge("ch_a"),
            _charge("ch_a"),
            _charge("ch_b"),
            _charge("ch_b"),
        ]
        result = detect_duplicates(charges)
        assert len(result) == 2
        ids = {d.charge_id for d in result}
        assert ids == {"ch_a", "ch_b"}
        assert all(d.kind == DiscrepancyKind.DUPLICATE_CHARGE_ID for d in result)

    def test_empty_input_returns_empty(self) -> None:
        assert detect_duplicates([]) == []

    def test_accepts_generator_input(self) -> None:
        """detect_duplicates must not re-iterate — it may be a one-shot generator."""

        def gen() -> Generator[StripeCharge, None, None]:
            yield _charge("ch_dup")
            yield _charge("ch_dup")

        result = detect_duplicates(gen())
        assert len(result) == 1
        assert result[0].kind == DiscrepancyKind.DUPLICATE_CHARGE_ID


class TestReconcileDuplicates:
    def test_duplicate_charges_emits_duplicate_discrepancy(
        self, store: OrdersStore
    ) -> None:
        charges = [_charge("ch_dup", 500), _charge("ch_dup", 500)]
        result = reconcile(charges, store)
        kinds = [d.kind for d in result]
        assert DiscrepancyKind.DUPLICATE_CHARGE_ID in kinds

    def test_duplicate_with_no_matching_order_emits_both_kinds(
        self, store: OrdersStore
    ) -> None:
        charges = [_charge("ch_dup", 200), _charge("ch_dup", 200)]
        result = reconcile(charges, store)
        kinds = {d.kind for d in result}
        assert DiscrepancyKind.DUPLICATE_CHARGE_ID in kinds
        assert DiscrepancyKind.CHARGE_NOT_IN_ORDERS in kinds

    def test_all_discrepancies_have_non_empty_detail(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        _seed_store(
            store,
            tmp_path,
            [
                ("ord_ghost", 999, "ch_ghost"),
                ("ord_mismatch", 500, "ch_mismatch"),
            ],
        )
        charges = [
            _charge("ch_mismatch", 600),
            _charge("ch_orphan", 800),
            _charge("ch_dup", 100),
            _charge("ch_dup", 100),
        ]
        result = reconcile(charges, store)
        assert result, "expected at least one discrepancy in this scenario"
        assert all(
            d.detail for d in result
        ), "every discrepancy must have a non-empty detail string"
