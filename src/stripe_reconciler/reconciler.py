"""Reconciler engine — joins Stripe charges to local orders and emits discrepancies."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from stripe_reconciler.models import (
    Discrepancy,
    DiscrepancyKind,
    LocalOrder,
    StripeCharge,
    StripeSubscription,
)
from stripe_reconciler.store import OrdersStore


def build_detail(
    kind: DiscrepancyKind,
    charge: StripeCharge | None,
    order: LocalOrder | None,
) -> str:
    """Render the human-readable detail string for a given discrepancy kind."""
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
                    detail=build_detail(DiscrepancyKind.DUPLICATE_CHARGE_ID, representative, None),
                )
            )
    return result


def _enrich_detail(
    discrepancy: Discrepancy,
    charge_map: dict[str, StripeCharge],
    sub_by_id: dict[str, StripeSubscription],
) -> Discrepancy:
    """Return discrepancy with subscription context appended when applicable.

    Only AMOUNT_MISMATCH and CHARGE_NOT_IN_ORDERS discrepancies whose
    originating charge carries a ``subscription_id`` metadata key and whose
    subscription is present in *sub_by_id* are modified.  All others pass
    through unchanged.
    """
    if discrepancy.kind not in (
        DiscrepancyKind.AMOUNT_MISMATCH,
        DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
    ):
        return discrepancy

    charge = charge_map.get(discrepancy.charge_id or "")
    if charge is None:
        return discrepancy

    sub_id = charge.metadata.get("subscription_id")
    if not sub_id:
        return discrepancy

    sub = sub_by_id.get(sub_id)
    if sub is None:
        return discrepancy

    return discrepancy.model_copy(
        update={"detail": f"{discrepancy.detail}; subscription: {sub_id} ({sub.status})"}
    )


def reconcile(
    charges: Iterable[StripeCharge],
    store: OrdersStore,
    *,
    subscriptions: Iterable[StripeSubscription] | None = None,
) -> list[Discrepancy]:
    charges_list: list[StripeCharge] = list(charges)
    result: list[Discrepancy] = detect_duplicates(charges_list)
    charge_map: dict[str, StripeCharge] = {c.id: c for c in charges_list}
    order_map: dict[str, LocalOrder] = {o.stripe_charge_id: o for o in store.get_all_orders()}

    for charge_id, order in order_map.items():
        if charge_id not in charge_map:
            result.append(Discrepancy(
                kind=DiscrepancyKind.ORDER_NOT_IN_STRIPE,
                charge_id=charge_id, order_id=order.order_id,
                stripe_amount_cents=None, order_amount_cents=order.amount_cents,
                detail=build_detail(DiscrepancyKind.ORDER_NOT_IN_STRIPE, None, order),
            ))

    for charge_id, charge in charge_map.items():
        if charge_id not in order_map:
            result.append(Discrepancy(
                kind=DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
                charge_id=charge_id, order_id=None,
                stripe_amount_cents=charge.amount, order_amount_cents=None,
                detail=build_detail(DiscrepancyKind.CHARGE_NOT_IN_ORDERS, charge, None),
            ))
        else:
            order = order_map[charge_id]
            if charge.amount != order.amount_cents:
                result.append(Discrepancy(
                    kind=DiscrepancyKind.AMOUNT_MISMATCH,
                    charge_id=charge_id, order_id=order.order_id,
                    stripe_amount_cents=charge.amount, order_amount_cents=order.amount_cents,
                    detail=build_detail(DiscrepancyKind.AMOUNT_MISMATCH, charge, order),
                ))

    if subscriptions is not None:
        sub_by_id: dict[str, StripeSubscription] = {s.id: s for s in subscriptions}
        result = [_enrich_detail(d, charge_map, sub_by_id) for d in result]

    return result
