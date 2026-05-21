"""Unit tests for fetch_all_charges cursor pagination.

Verifies the two-page pagination contract (ch_a/ch_b/ch_c → ch_d/ch_e) and
the empty-response short-circuit path.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, call

from stripe_reconciler.client import StripeClient
from stripe_reconciler.fetchers.charges import fetch_all_charges
from stripe_reconciler.models import StripeCharge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _page(charges: list[MagicMock], *, has_more: bool) -> MagicMock:
    page: MagicMock = MagicMock()
    page.data = charges
    page.has_more = has_more
    return page


# ---------------------------------------------------------------------------
# Two-page pagination: ch_a/ch_b/ch_c → ch_d/ch_e
# ---------------------------------------------------------------------------


class TestTwoPagePagination:
    """Page 1 returns has_more=True with ch_a/ch_b/ch_c; page 2 returns has_more=False."""

    def _make_mock(self) -> MagicMock:
        mock: MagicMock = MagicMock()
        mock.list_charges.side_effect = [
            _page(
                [_raw_charge("ch_a"), _raw_charge("ch_b"), _raw_charge("ch_c")],
                has_more=True,
            ),
            _page(
                [_raw_charge("ch_d"), _raw_charge("ch_e")],
                has_more=False,
            ),
        ]
        return mock

    def test_yields_five_stripe_charge_objects(self) -> None:
        """All 5 charges across both pages are yielded as StripeCharge instances."""
        mock = self._make_mock()

        result = list(fetch_all_charges(cast(StripeClient, mock), None, None, 3))

        assert len(result) == 5
        assert all(isinstance(c, StripeCharge) for c in result)
        assert [c.id for c in result] == ["ch_a", "ch_b", "ch_c", "ch_d", "ch_e"]

    def test_list_charges_called_exactly_twice(self) -> None:
        """The pagination loop makes exactly 2 API calls — one per page."""
        mock = self._make_mock()

        list(fetch_all_charges(cast(StripeClient, mock), None, None, 3))

        assert mock.list_charges.call_count == 2

    def test_second_call_uses_starting_after_ch_c(self) -> None:
        """Second call passes starting_after='ch_c' (last id from page 1)."""
        mock = self._make_mock()

        list(fetch_all_charges(cast(StripeClient, mock), None, None, 3))

        _first, second = mock.list_charges.call_args_list
        assert second == call(
            starting_after="ch_c",
            limit=3,
            created_gte=None,
            created_lte=None,
        )

    def test_first_call_starts_without_cursor(self) -> None:
        """First call always passes starting_after=None (no prior checkpoint)."""
        mock = self._make_mock()

        list(fetch_all_charges(cast(StripeClient, mock), None, None, 3))

        first, _second = mock.list_charges.call_args_list
        assert first == call(
            starting_after=None,
            limit=3,
            created_gte=None,
            created_lte=None,
        )


# ---------------------------------------------------------------------------
# Empty-response case
# ---------------------------------------------------------------------------


class TestEmptyResponse:
    def test_empty_first_page_yields_no_charges(self) -> None:
        """An empty first page produces zero StripeCharge objects."""
        mock: MagicMock = MagicMock()
        mock.list_charges.return_value = _page([], has_more=False)

        result = list(fetch_all_charges(cast(StripeClient, mock), None, None, 10))

        assert result == []

    def test_empty_first_page_makes_exactly_one_api_call(self) -> None:
        """Loop terminates immediately on has_more=False; no further calls are made."""
        mock: MagicMock = MagicMock()
        mock.list_charges.return_value = _page([], has_more=False)

        list(fetch_all_charges(cast(StripeClient, mock), None, None, 10))

        assert mock.list_charges.call_count == 1
