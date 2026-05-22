"""Cursor-paginated Stripe subscriptions fetcher."""
from __future__ import annotations

from collections.abc import Iterator

from stripe_reconciler.client import StripeClient
from stripe_reconciler.models import StripeSubscription


def fetch_subscriptions(
    client: StripeClient,
    page_size: int = 100,
) -> Iterator[StripeSubscription]:
    """Yield all Stripe subscriptions via cursor-based pagination.

    Args:
        client: Authenticated :class:`~stripe_reconciler.client.StripeClient`.
        page_size: Subscriptions per API call (1–100).

    Yields:
        :class:`~stripe_reconciler.models.StripeSubscription` objects.
    """
    cursor: str | None = None
    while True:
        page = client.list_subscriptions(starting_after=cursor, limit=page_size)
        for raw in page.data:
            yield StripeSubscription(id=raw.id, status=raw.status)
        if not page.has_more:
            break
        cursor = page.data[-1].id
