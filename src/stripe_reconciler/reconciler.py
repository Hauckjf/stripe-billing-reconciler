"""Reconciler engine — joins Stripe charges to local orders and emits discrepancies."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from stripe_reconciler.models import (
    Discrepancy,
    DiscrepancyKind,
    LocalOrder,
    StripeCharge,
)
from stripe_reconciler.store import OrdersStore


def build_detail(
    kind: DiscrepancyKind,
    charge: StripeCharge | None,
    order: LocalOrder | None,
) -> str:
    """Return a human-readable one-line explanation for a discrepancy.

    Args:
        kind: Classification bucket for the discrepancy.
        charge: The Stripe charge involved, or ``None`` when the charge is
            absent from the Stripe response (``ORDER_NOT_IN_STRIPE``).
        order: The local order involved, or ``None`` when there is no
            matching order (``CHARGE_NOT_IN_ORDERS``, ``DUPLICATE_CHARGE_ID``).

    Returns:
        A non-empty string suitable for inclusion in a discrepancy report.
    """
    if kind is DiscrepancyKind.AMOUNT_MISMATCH:
        assert charge is not None
        assert order is not None
        delta = charge.amount - order.amount_cents
        return (
            f"order {order.order_id} expects {order.amount_cents} cents,"
            f" Stripe reports {charge.amount} cents (delta: {delta:+d})"
        )
    if kind is DiscrepancyKind.CHARGE_NOT_IN_ORDERS:
        assert charge is not None
        return f"Stripe charge {charge.id!r} has no matching local order"
    if kind is DiscrepancyKind.ORDER_NOT_IN_STRIPE:
        assert order is not None
        return (
            f"order {order.order_id!r} references charge"
            f" {order.stripe_charge_id!r} not returned by Stripe"
        )
    # DiscrepancyKind.DUPLICATE_CHARGE_ID
    assert charge is not None
    return f"Stripe charge {charge.id!r} appears more than once in the input"


def detect_duplicates(charges: Iterable[StripeCharge]) -> list[Discrepancy]:
    """Scan *charges* for duplicate charge IDs and emit one discrepancy per group.

    Args:
        charges: Stripe charge records to scan.  Consumed exactly once.

    Returns:
        One :class:`~stripe_reconciler.models.Discrepancy` per duplicate
        group (i.e. per charge ID that appears more than once in the input).
        An empty list means no duplicates were found.
    """
    groups: dict[str, list[StripeCharge]] = defaultdict(list)
    for charge in charges:
        groups[charge.id].append(charge)

    result: list[Discrepancy] = []
    for charge_id, group in groups.items():
        if len(group) > 1:
            representative = group[0]
            result.append(
                Discrepancy(
                    kind=DiscrepancyKind.DUPLICATE_CHARGE_ID,
                    charge_id=charge_id,
                    order_id=None,
                    stripe_amount_cents=representative.amount,
                    order_amount_cents=None,
                    detail=build_detail(
                        DiscrepancyKind.DUPLICATE_CHARGE_ID,
                        representative,
                        None,
                    ),
                )
            )
    return result


def reconcile(charges: Iterable[StripeCharge], store: OrdersStore) -> list[Discrepancy]:
    """Cross-reference Stripe charges against local orders and return discrepancies.

    Pure function — reads from *store* but performs no writes or network I/O.

    Detection rules applied:

    - ``DUPLICATE_CHARGE_ID``: the same charge ID appears more than once in *charges*.
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
    charges_list: list[StripeCharge] = list(charges)
    result: list[Discrepancy] = detect_duplicates(charges_list)

    charge_map: dict[str, StripeCharge] = {c.id: c for c in charges_list}
    order_map: dict[str, LocalOrder] = {
        o.stripe_charge_id: o for o in store.get_all_orders()
    }

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
                    detail=build_detail(DiscrepancyKind.ORDER_NOT_IN_STRIPE, None, order),
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
                    detail=build_detail(DiscrepancyKind.CHARGE_NOT_IN_ORDERS, charge, None),
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
                        detail=build_detail(DiscrepancyKind.AMOUNT_MISMATCH, charge, order),
                    )
                )

    return result
