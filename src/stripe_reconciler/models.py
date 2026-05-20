"""Domain models for Stripe charges, local orders, and reconciliation discrepancies."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StripeCharge(BaseModel):
    """A charge record fetched from the Stripe API."""

    model_config = ConfigDict(frozen=True)

    id: str
    amount: int
    currency: str
    created: datetime
    status: str


class LocalOrder(BaseModel):
    """A row from the internal orders table."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    amount_cents: int
    stripe_charge_id: str
    created_at: datetime


class DiscrepancyKind(str, enum.Enum):
    """Classification bucket for a reconciliation discrepancy."""

    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    CHARGE_NOT_IN_ORDERS = "CHARGE_NOT_IN_ORDERS"
    ORDER_NOT_IN_STRIPE = "ORDER_NOT_IN_STRIPE"
    DUPLICATE_CHARGE_ID = "DUPLICATE_CHARGE_ID"


class Discrepancy(BaseModel):
    """A single reconciliation discrepancy between Stripe data and local orders."""

    model_config = ConfigDict(frozen=True)

    kind: DiscrepancyKind
    charge_id: str | None
    order_id: str | None
    stripe_amount_cents: int | None
    order_amount_cents: int | None
    detail: str
