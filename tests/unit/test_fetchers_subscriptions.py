"""Behavioural tests for the cursor-paginated subscriptions fetcher."""
from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, call

from stripe_reconciler.client import StripeClient
from stripe_reconciler.fetchers.subscriptions import fetch_subscriptions
from stripe_reconciler.models import StripeSubscription


def _raw_sub(sub_id: str, *, status: str = "active") -> MagicMock:
    raw: MagicMock = MagicMock()
    raw.id = sub_id
    raw.status = status
    return raw


def _page(subs: list[Any], *, has_more: bool) -> MagicMock:
    page: MagicMock = MagicMock()
    page.data = subs
    page.has_more = has_more
    return page


class TestFetchSubscriptions:
    def test_single_page_yields_all_subscriptions(self) -> None:
        """One page with 3 subscriptions → 3 StripeSubscription objects."""
        mock: MagicMock = MagicMock()
        mock.list_subscriptions.return_value = _page(
            [_raw_sub(f"sub_{i}") for i in range(3)], has_more=False
        )

        result = list(fetch_subscriptions(cast(StripeClient, mock), page_size=100))

        assert len(result) == 3
        assert all(isinstance(s, StripeSubscription) for s in result)
        assert [s.id for s in result] == ["sub_0", "sub_1", "sub_2"]

    def test_two_pages_yields_all_subscriptions_in_order(self) -> None:
        """Two pages of 2 subscriptions each → 4 objects preserving insertion order."""
        page1 = _page([_raw_sub(f"sub_a{i}") for i in range(2)], has_more=True)
        page2 = _page([_raw_sub(f"sub_b{i}") for i in range(2)], has_more=False)
        mock: MagicMock = MagicMock()
        mock.list_subscriptions.side_effect = [page1, page2]

        result = list(fetch_subscriptions(cast(StripeClient, mock), page_size=2))

        assert len(result) == 4
        assert [s.id for s in result] == ["sub_a0", "sub_a1", "sub_b0", "sub_b1"]

    def test_cursor_advances_to_last_id_of_previous_page(self) -> None:
        """Second call receives starting_after equal to the last sub id from page 1."""
        page1 = _page([_raw_sub(f"sub_{i}") for i in range(3)], has_more=True)
        page2 = _page([_raw_sub(f"sub_{i + 3}") for i in range(3)], has_more=False)
        mock: MagicMock = MagicMock()
        mock.list_subscriptions.side_effect = [page1, page2]

        list(fetch_subscriptions(cast(StripeClient, mock), page_size=3))

        first, second = mock.list_subscriptions.call_args_list
        assert first == call(starting_after=None, limit=3)
        assert second == call(starting_after="sub_2", limit=3)

    def test_status_preserved_on_each_subscription(self) -> None:
        """status field is correctly mapped from the raw Stripe object."""
        mock: MagicMock = MagicMock()
        mock.list_subscriptions.return_value = _page(
            [
                _raw_sub("sub_active", status="active"),
                _raw_sub("sub_past_due", status="past_due"),
                _raw_sub("sub_canceled", status="canceled"),
            ],
            has_more=False,
        )

        result = list(fetch_subscriptions(cast(StripeClient, mock)))

        statuses = [s.status for s in result]
        assert statuses == ["active", "past_due", "canceled"]

    def test_empty_page_yields_nothing(self) -> None:
        """Empty first page terminates with no output and exactly one API call."""
        mock: MagicMock = MagicMock()
        mock.list_subscriptions.return_value = _page([], has_more=False)

        result = list(fetch_subscriptions(cast(StripeClient, mock)))

        assert result == []
        assert mock.list_subscriptions.call_count == 1

    def test_stops_after_has_more_false(self) -> None:
        """Loop terminates after the first page when has_more=False."""
        mock: MagicMock = MagicMock()
        mock.list_subscriptions.return_value = _page(
            [_raw_sub("sub_only")], has_more=False
        )

        list(fetch_subscriptions(cast(StripeClient, mock), page_size=50))

        assert mock.list_subscriptions.call_count == 1

    def test_makes_exactly_two_api_calls_for_two_pages(self) -> None:
        """Cursor loop calls the API once per page and stops at has_more=False."""
        page1 = _page([_raw_sub(f"sub_{i}") for i in range(3)], has_more=True)
        page2 = _page([_raw_sub(f"sub_{i + 3}") for i in range(3)], has_more=False)
        mock: MagicMock = MagicMock()
        mock.list_subscriptions.side_effect = [page1, page2]

        list(fetch_subscriptions(cast(StripeClient, mock), page_size=3))

        assert mock.list_subscriptions.call_count == 2
