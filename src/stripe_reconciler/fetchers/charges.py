"""Cursor-paginated Stripe charges fetcher."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from stripe_reconciler.client import StripeClient
from stripe_reconciler.models import StripeCharge


def _iter_mock_charges(path: str | Path) -> Iterator[StripeCharge]:
    """Yield StripeCharge objects from a local Stripe-style charges.list JSON file.

    Used exclusively when the ``STRIPE_MOCK_CHARGES_FILE`` environment variable
    is set (e.g. by ``examples/run_local_demo.sh``).  Has no effect in normal
    production usage.
    """
    with open(path) as fh:
        payload = json.load(fh)
    for raw in payload.get("data", []):
        yield StripeCharge(
            id=raw["id"],
            amount=raw["amount"],
            currency=raw["currency"],
            created=datetime.fromtimestamp(raw["created"], tz=timezone.utc),
            status=raw["status"],
        )


def fetch_all_charges(
    client: StripeClient,
    created_gte: datetime | None,
    created_lte: datetime | None,
    page_size: int,
) -> Iterator[StripeCharge]:
    """Yield every Stripe charge in the given date window via cursor pagination.

    When the ``STRIPE_MOCK_CHARGES_FILE`` environment variable points to a local
    JSON file, charges are read from that file instead of hitting the live Stripe
    API.  The file must contain a Stripe-style ``charges.list`` response body:
    ``{"data": [{id, amount, currency, created, status}, ...], ...}``.
    Date filtering is bypassed in mock mode; all records in the file are yielded.

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
    mock_path = os.environ.get("STRIPE_MOCK_CHARGES_FILE")
    if mock_path:
        yield from _iter_mock_charges(mock_path)
        return

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
