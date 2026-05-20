from __future__ import annotations

import logging
from typing import Any

import stripe
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_RETRYABLE: tuple[type[Exception], ...] = (
    stripe.error.RateLimitError,
    stripe.error.APIConnectionError,
)


def _build_created_filter(
    gte: int | None,
    lte: int | None,
) -> dict[str, int] | None:
    """Return a Stripe `created` range dict, or None when no bounds are given."""
    if gte is None and lte is None:
        return None
    result: dict[str, int] = {}
    if gte is not None:
        result["gte"] = gte
    if lte is not None:
        result["lte"] = lte
    return result


class StripeClient:
    """Stripe SDK wrapper with tenacity retry on transient errors.

    Retries ``RateLimitError`` and ``APIConnectionError`` with exponential
    backoff (multiplier=2, ceiling=60 s).  ``AuthenticationError`` is never
    retried — it is a hard, non-transient failure.
    """

    def __init__(self, api_key: str, max_retries: int = 5) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        stripe.api_key = api_key
        self._max_retries = max_retries
        self._retry = retry(
            retry=retry_if_exception_type(_RETRYABLE),
            wait=wait_exponential(multiplier=2, max=60),
            stop=stop_after_attempt(max_retries),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

    def list_charges(
        self,
        starting_after: str | None = None,
        limit: int = 100,
        created_gte: int | None = None,
        created_lte: int | None = None,
    ) -> stripe.ListObject:  # type: ignore[type-arg]
        """Return one cursor-paginated page of Stripe charges.

        Args:
            starting_after: ID of the last object in the previous page (cursor).
            limit: Maximum objects to return per page (1–100).
            created_gte: Unix timestamp lower bound, inclusive.
            created_lte: Unix timestamp upper bound, inclusive.

        Returns:
            A :class:`stripe.ListObject` whose ``.data`` contains
            :class:`stripe.Charge` objects and ``.has_more`` signals
            whether another page is available.
        """
        params: dict[str, Any] = {"limit": limit}
        if starting_after is not None:
            params["starting_after"] = starting_after
        created = _build_created_filter(created_gte, created_lte)
        if created is not None:
            params["created"] = created

        def _call() -> Any:
            return stripe.Charge.list(**params)

        return self._retry(_call)()  # type: ignore[no-any-return]

    def list_events(
        self,
        starting_after: str | None = None,
        limit: int = 100,
        types: list[str] | None = None,
        created_gte: int | None = None,
        created_lte: int | None = None,
    ) -> stripe.ListObject:  # type: ignore[type-arg]
        """Return one cursor-paginated page of Stripe events.

        Args:
            starting_after: ID of the last object in the previous page (cursor).
            limit: Maximum objects to return per page (1–100).
            types: Event type strings to filter by; ``None`` returns all types.
            created_gte: Unix timestamp lower bound, inclusive.
            created_lte: Unix timestamp upper bound, inclusive.

        Returns:
            A :class:`stripe.ListObject` whose ``.data`` contains
            :class:`stripe.Event` objects and ``.has_more`` signals
            whether another page is available.
        """
        params: dict[str, Any] = {"limit": limit}
        if starting_after is not None:
            params["starting_after"] = starting_after
        if types:
            params["types"] = types
        created = _build_created_filter(created_gte, created_lte)
        if created is not None:
            params["created"] = created

        def _call() -> Any:
            return stripe.Event.list(**params)

        return self._retry(_call)()  # type: ignore[no-any-return]
