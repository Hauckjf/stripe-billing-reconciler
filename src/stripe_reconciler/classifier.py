"""Discrepancy classifier with configurable amount-tolerance window."""
from __future__ import annotations

from stripe_reconciler.models import (
    Discrepancy,
    DiscrepancyKind,
    LocalOrder,
    StripeCharge,
)


class DiscrepancyClassifier:
    """Classifies charge-order pairs into typed discrepancy kinds.

    The tolerance window lets callers accept small rounding differences —
    e.g. multi-currency conversions where Stripe and the local ledger apply
    different rounding modes when converting fractional cents.
    """

    def __init__(self, tolerance_cents: int = 0) -> None:
        """Initialize the classifier.

        Args:
            tolerance_cents: Absolute amount delta (inclusive) that is NOT
                flagged as AMOUNT_MISMATCH. Must be >= 0. Defaults to 0
                (exact match required).

        Raises:
            ValueError: If tolerance_cents is negative.
        """
        if tolerance_cents < 0:
            raise ValueError(
                f"tolerance_cents must be >= 0, got {tolerance_cents}"
            )
        self.tolerance_cents = tolerance_cents

    def classify_pair(
        self,
        charge: StripeCharge,
        order: LocalOrder,
    ) -> Discrepancy | None:
        """Classify a matched charge-order pair.

        Returns ``None`` when amounts agree within tolerance (clean match).
        Returns an ``AMOUNT_MISMATCH`` discrepancy when the absolute delta
        exceeds the configured tolerance.

        Args:
            charge: Stripe charge record.
            order: Matching local order (same ``stripe_charge_id``).

        Returns:
            A :class:`~stripe_reconciler.models.Discrepancy` when mismatched
            beyond tolerance, else ``None``.
        """
        delta = abs(charge.amount - order.amount_cents)
        if delta <= self.tolerance_cents:
            return None
        signed_delta = charge.amount - order.amount_cents
        return Discrepancy(
            kind=DiscrepancyKind.AMOUNT_MISMATCH,
            charge_id=charge.id,
            order_id=order.order_id,
            stripe_amount_cents=charge.amount,
            order_amount_cents=order.amount_cents,
            detail=(
                f"order {order.order_id} expects {order.amount_cents} cents,"
                f" Stripe reports {charge.amount} cents (delta: {signed_delta:+d})"
            ),
        )

    def classify_charge_not_in_orders(self, charge: StripeCharge) -> Discrepancy:
        """Return a CHARGE_NOT_IN_ORDERS discrepancy for an unmatched Stripe charge.

        Args:
            charge: Stripe charge with no matching local order.

        Returns:
            A :class:`~stripe_reconciler.models.Discrepancy` of kind
            ``CHARGE_NOT_IN_ORDERS``.
        """
        return Discrepancy(
            kind=DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
            charge_id=charge.id,
            order_id=None,
            stripe_amount_cents=charge.amount,
            order_amount_cents=None,
            detail=f"Stripe charge {charge.id!r} has no matching local order",
        )

    def classify_order_not_in_stripe(self, order: LocalOrder) -> Discrepancy:
        """Return an ORDER_NOT_IN_STRIPE discrepancy for an unmatched local order.

        Args:
            order: Local order whose ``stripe_charge_id`` was absent from the
                Stripe API response.

        Returns:
            A :class:`~stripe_reconciler.models.Discrepancy` of kind
            ``ORDER_NOT_IN_STRIPE``.
        """
        return Discrepancy(
            kind=DiscrepancyKind.ORDER_NOT_IN_STRIPE,
            charge_id=order.stripe_charge_id,
            order_id=order.order_id,
            stripe_amount_cents=None,
            order_amount_cents=order.amount_cents,
            detail=(
                f"order {order.order_id!r} references charge"
                f" {order.stripe_charge_id!r} not returned by Stripe"
            ),
        )
