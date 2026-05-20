"""Cursor-paginated Stripe charges fetcher."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from stripe_reconciler.client import StripeClient
from stripe_reconciler.models import StripeCharge


def fetch_all_charges(
    client: StripeClient,
    created_gte: datetime | None,
    created_lte: datetime | None,
    page_size: int,
) -> Iterator[StripeCharge]:
    """Yield every Stripe charge in the given date window via cursor pagination.

    Converts each charge's epoch ``created`` int to a UTC-aware
    :class:`~datetime.datetime`.  Stops automatically when Stripe's
    ``has_more`` flag becomes ``False`` so the caller never over-fetches.

    Args:
        client: Authenticated :class:`~stripe_reconciler.client.StripeClient`.
        created_gte: Inclusive lower bound on charge creation time;
            ``None`` omits the filter.
        created_lte: Inclusive upper bound on charge creation time;
            ``None`` omits the filter.
        page_size: Charges per API call (1\u2013100), forwarded as Stripe's ``limit``.

    Yields:
        :class:`~stripe_reconciler.models.StripeCharge` in the order returned
        by Stripe (newest-first by default).
    """
    cursor: str | None = None

    while True:
        page = client.list_charges(
            starting_after=cursor,
            limit=page_size,
            created_gte=int(created_gte.timestamp()) if created_gte is not None else None,
            created_lte=int(created_lte.timestamp()) if created_lte is not None else None,
        )

        for raw in page.data:  # type: ignore[union-attr]
            yield StripeCharge(
                id=raw.id,
                amount=raw.amount,
                currency=raw.currency,
                created=datetime.fromtimestamp(raw.created, tz=timezone.utc),
                status=raw.status,
            )

        if not page.has_more:  # type: ignore[union-attr]
            break

        cursor = page.data[-1].id  # type: ignore[union-attr]
