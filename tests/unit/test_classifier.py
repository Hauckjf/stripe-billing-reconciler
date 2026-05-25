"""Unit tests for DiscrepancyClassifier — pure-domain logic, no I/O."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stripe_reconciler.classifier import DiscrepancyClassifier
from stripe_reconciler.models import (
    Discrepancy,
    DiscrepancyKind,
    LocalOrder,
    StripeCharge,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _charge(charge_id: str, amount: int, currency: str = "usd") -> StripeCharge:
    return StripeCharge(
        id=charge_id,
        amount=amount,
        currency=currency,
        created=datetime(2024, 3, 1, tzinfo=timezone.utc),
        status="succeeded",
    )


def _order(order_id: str, amount_cents: int, stripe_charge_id: str) -> LocalOrder:
    return LocalOrder(
        order_id=order_id,
        amount_cents=amount_cents,
        stripe_charge_id=stripe_charge_id,
        created_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
    )


# ── Constructor ─────────────────────────────────────────────────────────────


class TestConstructor:
    def test_default_tolerance_is_zero(self) -> None:
        """Default constructor requires exact amount match."""
        c = DiscrepancyClassifier()
        assert c.tolerance_cents == 0

    def test_positive_tolerance_accepted(self) -> None:
        c = DiscrepancyClassifier(tolerance_cents=5)
        assert c.tolerance_cents == 5

    def test_negative_tolerance_raises(self) -> None:
        """Negative tolerance is nonsensical — must surface at construction."""
        with pytest.raises(ValueError, match="tolerance_cents must be >= 0"):
            DiscrepancyClassifier(tolerance_cents=-1)


# ── classify_pair ───────────────────────────────────────────────────────────


class TestClassifyPair:
    def test_exact_match_returns_none(self) -> None:
        """A clean match (amounts equal) must return None."""
        result = DiscrepancyClassifier().classify_pair(
            _charge("ch_1", 1000),
            _order("ord_1", 1000, "ch_1"),
        )
        assert result is None

    def test_amount_mismatch_above_tolerance(self) -> None:
        """Delta exceeding tolerance produces AMOUNT_MISMATCH."""
        result = DiscrepancyClassifier(tolerance_cents=2).classify_pair(
            _charge("ch_1", 1003),
            _order("ord_1", 1000, "ch_1"),
        )
        assert isinstance(result, Discrepancy)
        assert result.kind == DiscrepancyKind.AMOUNT_MISMATCH
        assert result.charge_id == "ch_1"
        assert result.order_id == "ord_1"
        assert result.stripe_amount_cents == 1003
        assert result.order_amount_cents == 1000

    def test_amount_mismatch_at_tolerance_boundary_inclusive(self) -> None:
        """Delta equal to tolerance must NOT be flagged (inclusive bound)."""
        result = DiscrepancyClassifier(tolerance_cents=2).classify_pair(
            _charge("ch_1", 1002),
            _order("ord_1", 1000, "ch_1"),
        )
        assert result is None

    def test_amount_mismatch_at_tolerance_plus_one_is_flagged(self) -> None:
        """One cent above tolerance must flag."""
        result = DiscrepancyClassifier(tolerance_cents=2).classify_pair(
            _charge("ch_1", 1003),
            _order("ord_1", 1000, "ch_1"),
        )
        assert result is not None
        assert result.kind == DiscrepancyKind.AMOUNT_MISMATCH

    def test_negative_delta_uses_absolute_value(self) -> None:
        """Tolerance check uses |delta|, so order > charge is also bounded."""
        # charge=1000, order=1003: order is 3 cents higher, delta=-3, |delta|=3 > tolerance=2
        result = DiscrepancyClassifier(tolerance_cents=2).classify_pair(
            _charge("ch_1", 1000),
            _order("ord_1", 1003, "ch_1"),
        )
        assert result is not None
        assert result.kind == DiscrepancyKind.AMOUNT_MISMATCH

    def test_signed_delta_shown_in_detail(self) -> None:
        """Detail string includes signed delta (positive when Stripe > order)."""
        result = DiscrepancyClassifier().classify_pair(
            _charge("ch_1", 1005),
            _order("ord_1", 1000, "ch_1"),
        )
        assert result is not None
        assert "+5" in result.detail or "delta: +5" in result.detail

    def test_negative_signed_delta_shown_in_detail(self) -> None:
        """Detail string includes signed delta (negative when Stripe < order)."""
        result = DiscrepancyClassifier().classify_pair(
            _charge("ch_1", 990),
            _order("ord_1", 1000, "ch_1"),
        )
        assert result is not None
        assert "-10" in result.detail


# ── classify_charge_not_in_orders ───────────────────────────────────────────


class TestChargeNotInOrders:
    def test_returns_typed_discrepancy(self) -> None:
        result = DiscrepancyClassifier().classify_charge_not_in_orders(
            _charge("ch_orphan", 2500),
        )
        assert result.kind == DiscrepancyKind.CHARGE_NOT_IN_ORDERS
        assert result.charge_id == "ch_orphan"
        assert result.order_id is None
        assert result.stripe_amount_cents == 2500
        assert result.order_amount_cents is None
        assert "ch_orphan" in result.detail


# ── classify_order_not_in_stripe ────────────────────────────────────────────


class TestOrderNotInStripe:
    def test_returns_typed_discrepancy(self) -> None:
        result = DiscrepancyClassifier().classify_order_not_in_stripe(
            _order("ord_orphan", 1500, "ch_missing"),
        )
        assert result.kind == DiscrepancyKind.ORDER_NOT_IN_STRIPE
        assert result.charge_id == "ch_missing"
        assert result.order_id == "ord_orphan"
        assert result.stripe_amount_cents is None
        assert result.order_amount_cents == 1500
        assert "ord_orphan" in result.detail
        assert "ch_missing" in result.detail
