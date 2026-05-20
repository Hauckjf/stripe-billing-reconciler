"""Reconciler engine — joins Stripe charges to local orders and emits discrepancies."""
from __future__ import annotations

from collections.abc import Iterable

from stripe_reconciler.models import (
    Discrepancy,
    DiscrepancyKind,
    LocalOrder,
    StripeCharge,
)
from stripe_reconciler.store import OrdersStore


def reconcile(charges: Iterable[StripeCharge], store: OrdersStore) -> list[Discrepancy]:
    """Cross-reference Stripe charges against local orders and return discrepancies.

    Pure function — reads from *store* but performs no writes or network I/O.

    Detection rules applied:

    - ``ORDER_NOT_IN_STRIPE``: local order references a charge_id absent from *charges*.
    - ``CHARGE_NOT_IN_ORDERS``: Stripe charge has no matching local order.
    - ``AMOUNT_MISMATCH``: both sides exist but ``charge.amount != order.amount_cents``.

    Args:
        charges: Stripe charge records for the reconciliation window.  Any
            :class:`~collections.abc.Iterable` is accepted; the sequence is
            consumed exactly once.
        store: Populated local orders store to cross-reference against.

    Returns:
        List of :class:`~stripe_reconciler.models.Discrepancy` objects.
        An empty list means a clean run with no discrepancies.
    """
    charge_map: dict[str, StripeCharge] = {c.id: c for c in charges}
    order_map: dict[str, LocalOrder] = {
        o.stripe_charge_id: o for o in store.get_all_orders()
    }

    result: list[Discrepancy] = []

    # Orders whose stripe_charge_id was not returned by Stripe
    for charge_id, order in order_map.items():
        if charge_id not in charge_map:
            result.append(
                Discrepancy(
                    kind=DiscrepancyKind.ORDER_NOT_IN_STRIPE,
                    charge_id=charge_id,
                    order_id=order.order_id,
                    stripe_amount_cents=None,
                    order_amount_cents=order.amount_cents,
                    detail=(
                        f"Order {order.order_id!r} references charge {charge_id!r}"
                        " not returned by Stripe"
                    ),
                )
            )

    # Stripe charges with no matching local order, or matched but amounts differ
    for charge_id, charge in charge_map.items():
        if charge_id not in order_map:
            result.append(
                Discrepancy(
                    kind=DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
                    charge_id=charge_id,
                    order_id=None,
                    stripe_amount_cents=charge.amount,
                    order_amount_cents=None,
                    detail=f"Stripe charge {charge_id!r} has no matching local order",
                )
            )
        else:
            order = order_map[charge_id]
            if charge.amount != order.amount_cents:
                result.append(
                    Discrepancy(
                        kind=DiscrepancyKind.AMOUNT_MISMATCH,
                        charge_id=charge_id,
                        order_id=order.order_id,
                        stripe_amount_cents=charge.amount,
                        order_amount_cents=order.amount_cents,
                        detail=(
                            f"Stripe amount {charge.amount} != order amount"
                            f" {order.amount_cents} for charge {charge_id!r}"
                        ),
                    )
                )

    return result
