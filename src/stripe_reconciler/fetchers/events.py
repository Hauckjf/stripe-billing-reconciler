"""Cursor-paginated Stripe subscription events fetcher."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from stripe_reconciler.client import StripeClient
from stripe_reconciler.models import StripeCharge

_SUBSCRIPTION_EVENT_TYPES: list[str] = [
    "invoice.payment_succeeded",
    "charge.succeeded",
]


def _charge_from_event(event: Any) -> StripeCharge | None:
    """Extract a StripeCharge from a Stripe event, or return None when data is absent.

    For ``charge.succeeded`` events the embedded object is already a Stripe
    Charge; only subscription charges — those linked to an invoice — are
    returned.  Bare one-off charges (no ``invoice`` reference) are skipped.

    For ``invoice.payment_succeeded`` events the embedded object is a Stripe
    Invoice.  The function inspects the ``charge`` attribute, which Stripe
    expands to a full Charge object when the event is fetched via the Events
    API with automatic expansion.  A bare string ID (unexpanded reference) or
    ``None`` (zero-amount or credit-note invoice) is treated as missing data
    and causes the event to be skipped.

    Returns:
        A fully-populated :class:`~stripe_reconciler.models.StripeCharge`, or
        ``None`` when the event carries insufficient charge data.
    """
    obj: Any = event.data.object
    event_type: str = event.type

    if event_type == "charge.succeeded":
        # Skip non-subscription charges: only those with an invoice reference
        # originated from subscription billing.
        if not getattr(obj, "invoice", None):
            return None
        charge_obj: Any = obj

    elif event_type == "invoice.payment_succeeded":
        # data.object is an Invoice.  The ``charge`` field is either None
        # ($0 invoice / credit note), an unexpanded string ID, or a full
        # Charge object when the Events API returns it expanded.
        charge_ref: Any = getattr(obj, "charge", None)
        if charge_ref is None or isinstance(charge_ref, str):
            return None
        charge_obj = charge_ref

    else:
        return None

    try:
        return StripeCharge(
            id=charge_obj.id,
            amount=charge_obj.amount,
            currency=charge_obj.currency,
            created=datetime.fromtimestamp(charge_obj.created, tz=timezone.utc),
            status=charge_obj.status,
        )
    except (AttributeError, TypeError):
        return None


def fetch_subscription_events(
    client: StripeClient,
    created_gte: datetime | None,
    created_lte: datetime | None,
    page_size: int,
) -> Iterator[StripeCharge]:
    """Yield StripeCharge objects extracted from subscription-related Stripe events.

    Fetches ``invoice.payment_succeeded`` and ``charge.succeeded`` events via
    cursor-based pagination.  Events whose ``data.object`` carries no usable
    charge data are skipped silently; only events that can be fully mapped to
    a :class:`~stripe_reconciler.models.StripeCharge` are yielded.

    An interrupted run can be resumed by the caller by passing a custom
    starting cursor; the internal loop itself advances the cursor automatically
    using the last event ID on each page.

    Args:
        client: Authenticated :class:`~stripe_reconciler.client.StripeClient`.
        created_gte: Inclusive lower bound on event creation time;
            ``None`` omits the filter.
        created_lte: Inclusive upper bound on event creation time;
            ``None`` omits the filter.
        page_size: Events per API call (1–100), forwarded as Stripe's ``limit``.

    Yields:
        :class:`~stripe_reconciler.models.StripeCharge` in the order returned
        by Stripe (newest-first by default).
    """
    cursor: str | None = None

    while True:
        page = client.list_events(
            starting_after=cursor,
            limit=page_size,
            types=_SUBSCRIPTION_EVENT_TYPES,
            created_gte=int(created_gte.timestamp()) if created_gte is not None else None,
            created_lte=int(created_lte.timestamp()) if created_lte is not None else None,
        )

        for raw in page.data:  # type: ignore[union-attr]
            charge = _charge_from_event(raw)
            if charge is not None:
                yield charge

        if not page.has_more:  # type: ignore[union-attr]
            break

        cursor = page.data[-1].id  # type: ignore[union-attr]
