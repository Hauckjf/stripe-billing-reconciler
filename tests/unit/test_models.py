"""Behavioural tests for domain models."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from stripe_reconciler.models import (
    Discrepancy,
    DiscrepancyKind,
    LocalOrder,
    StripeCharge,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class TestStripeCharge:
    def test_round_trips_all_fields(self) -> None:
        ts = _utcnow()
        charge = StripeCharge(
            id="ch_test_001",
            amount=1000,
            currency="usd",
            created=ts,
            status="succeeded",
        )
        assert charge.id == "ch_test_001"
        assert charge.amount == 1000
        assert charge.currency == "usd"
        assert charge.created == ts
        assert charge.status == "succeeded"

    def test_frozen_rejects_mutation(self) -> None:
        charge = StripeCharge(
            id="ch_test_002",
            amount=500,
            currency="brl",
            created=_utcnow(),
            status="pending",
        )
        with pytest.raises(ValidationError):
            charge.id = "mutated"  # type: ignore[misc]


class TestLocalOrder:
    def test_round_trips_all_fields(self) -> None:
        ts = _utcnow()
        order = LocalOrder(
            order_id="ord_001",
            amount_cents=2500,
            stripe_charge_id="ch_test_001",
            created_at=ts,
        )
        assert order.order_id == "ord_001"
        assert order.amount_cents == 2500
        assert order.stripe_charge_id == "ch_test_001"
        assert order.created_at == ts

    def test_frozen_rejects_mutation(self) -> None:
        order = LocalOrder(
            order_id="ord_002",
            amount_cents=100,
            stripe_charge_id="ch_test_002",
            created_at=_utcnow(),
        )
        with pytest.raises(ValidationError):
            order.order_id = "mutated"  # type: ignore[misc]


class TestDiscrepancyKind:
    def test_all_variants_defined(self) -> None:
        assert {k.value for k in DiscrepancyKind} == {
            "AMOUNT_MISMATCH",
            "CHARGE_NOT_IN_ORDERS",
            "ORDER_NOT_IN_STRIPE",
            "DUPLICATE_CHARGE_ID",
        }

    def test_is_str_enum(self) -> None:
        assert DiscrepancyKind.AMOUNT_MISMATCH == "AMOUNT_MISMATCH"
        assert isinstance(DiscrepancyKind.CHARGE_NOT_IN_ORDERS, str)


class TestDiscrepancy:
    def test_amount_mismatch_serializes_to_json(self) -> None:
        d = Discrepancy(
            kind=DiscrepancyKind.AMOUNT_MISMATCH,
            charge_id="ch_test_001",
            order_id="ord_001",
            stripe_amount_cents=1000,
            order_amount_cents=950,
            detail="Stripe amount 1000 != order amount 950",
        )
        payload = d.model_dump_json()
        parsed = json.loads(payload)
        assert parsed["kind"] == "AMOUNT_MISMATCH"
        assert parsed["charge_id"] == "ch_test_001"
        assert parsed["order_id"] == "ord_001"
        assert parsed["stripe_amount_cents"] == 1000
        assert parsed["order_amount_cents"] == 950

    def test_charge_not_in_orders_accepts_null_order_fields(self) -> None:
        d = Discrepancy(
            kind=DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
            charge_id="ch_orphan",
            order_id=None,
            stripe_amount_cents=500,
            order_amount_cents=None,
            detail="No matching order for charge ch_orphan",
        )
        assert d.order_id is None
        assert d.order_amount_cents is None
        parsed = json.loads(d.model_dump_json())
        assert parsed["order_id"] is None

    def test_order_not_in_stripe_accepts_null_charge_fields(self) -> None:
        d = Discrepancy(
            kind=DiscrepancyKind.ORDER_NOT_IN_STRIPE,
            charge_id=None,
            order_id="ord_orphan",
            stripe_amount_cents=None,
            order_amount_cents=1200,
            detail="Order ord_orphan has no corresponding Stripe charge",
        )
        assert d.charge_id is None
        assert d.stripe_amount_cents is None

    def test_duplicate_charge_id_all_optional_amounts_null(self) -> None:
        d = Discrepancy(
            kind=DiscrepancyKind.DUPLICATE_CHARGE_ID,
            charge_id="ch_dup",
            order_id=None,
            stripe_amount_cents=None,
            order_amount_cents=None,
            detail="Charge ID ch_dup appears in multiple orders",
        )
        assert d.kind == DiscrepancyKind.DUPLICATE_CHARGE_ID
        assert d.stripe_amount_cents is None
        assert d.order_amount_cents is None

    def test_frozen_rejects_mutation(self) -> None:
        d = Discrepancy(
            kind=DiscrepancyKind.AMOUNT_MISMATCH,
            charge_id="ch_001",
            order_id="ord_001",
            stripe_amount_cents=1000,
            order_amount_cents=900,
            detail="mismatch",
        )
        with pytest.raises(ValidationError):
            d.kind = DiscrepancyKind.ORDER_NOT_IN_STRIPE  # type: ignore[misc]
