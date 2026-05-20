"""Behavioural tests for the cursor-paginated charges fetcher."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock, call

from stripe_reconciler.client import StripeClient
from stripe_reconciler.fetchers.charges import fetch_all_charges
from stripe_reconciler.models import StripeCharge


def _raw_charge(
    charge_id: str,
    *,
    amount: int = 1_000,
    currency: str = "usd",
    created: int = 1_700_000_000,
    status: str = "succeeded",
) -> MagicMock:
    raw: MagicMock = MagicMock()
    raw.id = charge_id
    raw.amount = amount
    raw.currency = currency
    raw.created = created
    raw.status = status
    return raw


def _page(charges: list[Any], *, has_more: bool) -> MagicMock:
    page: MagicMock = MagicMock()
    page.data = charges
    page.has_more = has_more
    return page


class TestFetchAllCharges:
    def test_two_pages_yields_six_charges_in_order(self) -> None:
        """Two pages of 3 charges each \u2192 6 StripeCharge objects preserving order."""
        page1 = _page([_raw_charge(f"ch_a{i}") for i in range(3)], has_more=True)
        page2 = _page([_raw_charge(f"ch_b{i}") for i in range(3)], has_more=False)
        mock: MagicMock = MagicMock()
        mock.list_charges.side_effect = [page1, page2]

        result = list(fetch_all_charges(cast(StripeClient, mock), None, None, 3))

        assert len(result) == 6
        assert all(isinstance(c, StripeCharge) for c in result)
        assert [c.id for c in result] == [
            "ch_a0", "ch_a1", "ch_a2",
            "ch_b0", "ch_b1", "ch_b2",
        ]

    def test_makes_exactly_two_api_calls(self) -> None:
        """Cursor advances after the first page; loop exits after has_more=False."""
        page1 = _page([_raw_charge(f"ch_{i}") for i in range(3)], has_more=True)
        page2 = _page([_raw_charge(f"ch_{i + 3}") for i in range(3)], has_more=False)
        mock: MagicMock = MagicMock()
        mock.list_charges.side_effect = [page1, page2]

        list(fetch_all_charges(cast(StripeClient, mock), None, None, 3))

        assert mock.list_charges.call_count == 2

    def test_cursor_advances_to_last_id_of_previous_page(self) -> None:
        """Second call receives starting_after equal to the last charge id from page 1."""
        page1 = _page([_raw_charge(f"ch_{i}") for i in range(3)], has_more=True)
        page2 = _page([_raw_charge(f"ch_{i + 3}") for i in range(3)], has_more=False)
        mock: MagicMock = MagicMock()
        mock.list_charges.side_effect = [page1, page2]

        list(fetch_all_charges(cast(StripeClient, mock), None, None, 3))

        first, second = mock.list_charges.call_args_list
        assert first == call(starting_after=None, limit=3, created_gte=None, created_lte=None)
        assert second == call(starting_after="ch_2", limit=3, created_gte=None, created_lte=None)

    def test_epoch_created_converted_to_utc_datetime(self) -> None:
        """Stripe's epoch int on each charge maps to a timezone-aware UTC datetime."""
        epoch = 1_700_000_000
        mock: MagicMock = MagicMock()
        mock.list_charges.return_value = _page(
            [_raw_charge("ch_ts", created=epoch)], has_more=False
        )

        result = list(fetch_all_charges(cast(StripeClient, mock), None, None, 10))

        assert len(result) == 1
        expected = datetime.fromtimestamp(epoch, tz=timezone.utc)
        assert result[0].created == expected
        assert result[0].created.tzinfo is not None

    def test_single_page_stops_after_one_call(self) -> None:
        """When has_more is False on the first page, exactly one API call is made."""
        mock: MagicMock = MagicMock()
        mock.list_charges.return_value = _page([_raw_charge("ch_only")], has_more=False)

        result = list(fetch_all_charges(cast(StripeClient, mock), None, None, 10))

        assert len(result) == 1
        assert mock.list_charges.call_count == 1

    def test_empty_page_yields_nothing(self) -> None:
        """An empty first page terminates immediately with no output."""
        mock: MagicMock = MagicMock()
        mock.list_charges.return_value = _page([], has_more=False)

        result = list(fetch_all_charges(cast(StripeClient, mock), None, None, 10))

        assert result == []
        assert mock.list_charges.call_count == 1

    def test_date_bounds_forwarded_as_epoch_ints(self) -> None:
        """created_gte and created_lte datetime values are passed as epoch ints."""
        mock: MagicMock = MagicMock()
        mock.list_charges.return_value = _page([], has_more=False)
        gte = datetime(2024, 1, 1, tzinfo=timezone.utc)
        lte = datetime(2024, 1, 31, tzinfo=timezone.utc)

        list(fetch_all_charges(cast(StripeClient, mock), gte, lte, 10))

        mock.list_charges.assert_called_once_with(
            starting_after=None,
            limit=10,
            created_gte=int(gte.timestamp()),
            created_lte=int(lte.timestamp()),
        )

    def test_none_bounds_forwarded_as_none(self) -> None:
        """When no date range is given, None is passed for both epoch int params."""
        mock: MagicMock = MagicMock()
        mock.list_charges.return_value = _page([], has_more=False)

        list(fetch_all_charges(cast(StripeClient, mock), None, None, 10))

        mock.list_charges.assert_called_once_with(
            starting_after=None, limit=10, created_gte=None, created_lte=None
        )
