"""Behavioural tests for the cursor-paginated subscription events fetcher."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock, call

from stripe_reconciler.client import StripeClient
from stripe_reconciler.fetchers.events import fetch_subscription_events
from stripe_reconciler.models import StripeCharge


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _raw_charge_obj(
    charge_id: str,
    *,
    amount: int = 2_000,
    currency: str = "usd",
    created: int = 1_700_000_000,
    status: str = "succeeded",
    invoice: str | None = "in_test",
) -> MagicMock:
    obj: MagicMock = MagicMock()
    obj.id = charge_id
    obj.amount = amount
    obj.currency = currency
    obj.created = created
    obj.status = status
    obj.invoice = invoice
    return obj


def _charge_succeeded_event(charge_id: str, **kwargs: Any) -> MagicMock:
    """Build a charge.succeeded event whose data.object is a Charge mock."""
    event: MagicMock = MagicMock()
    event.type = "charge.succeeded"
    event.id = f"evt_{charge_id}"
    event.data.object = _raw_charge_obj(charge_id, **kwargs)
    return event


def _invoice_payment_event(
    event_id: str,
    *,
    charge_obj: Any = None,
) -> MagicMock:
    """Build an invoice.payment_succeeded event whose data.object is an Invoice mock."""
    invoice: MagicMock = MagicMock()
    invoice.charge = charge_obj  # None, string ID, or expanded Charge object
    event: MagicMock = MagicMock()
    event.type = "invoice.payment_succeeded"
    event.id = event_id
    event.data.object = invoice
    return event


def _page(events: list[Any], *, has_more: bool) -> MagicMock:
    page: MagicMock = MagicMock()
    page.data = events
    page.has_more = has_more
    return page


# ---------------------------------------------------------------------------
# Empty page
# ---------------------------------------------------------------------------


class TestEmptyEventList:
    def test_empty_page_yields_nothing_and_makes_one_call(self) -> None:
        """An empty first page terminates immediately without raising."""
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([], has_more=False)

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert result == []
        assert mock.list_events.call_count == 1


# ---------------------------------------------------------------------------
# charge.succeeded events
# ---------------------------------------------------------------------------


class TestChargeSucceededEvents:
    def test_subscription_charge_yields_stripe_charge(self) -> None:
        """charge.succeeded linked to an invoice is returned as a StripeCharge."""
        event = _charge_succeeded_event("ch_sub", amount=3_500, currency="brl", invoice="in_001")
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([event], has_more=False)

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert len(result) == 1
        assert isinstance(result[0], StripeCharge)
        assert result[0].id == "ch_sub"
        assert result[0].amount == 3_500
        assert result[0].currency == "brl"
        assert result[0].status == "succeeded"

    def test_non_subscription_charge_is_skipped(self) -> None:
        """charge.succeeded without an invoice reference is not subscription-related → skipped."""
        event = _charge_succeeded_event("ch_oneoff", invoice=None)
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([event], has_more=False)

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert result == []

    def test_epoch_created_converted_to_utc_aware_datetime(self) -> None:
        """Stripe's epoch int maps to a timezone-aware UTC datetime."""
        epoch = 1_700_000_000
        event = _charge_succeeded_event("ch_ts", created=epoch)
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([event], has_more=False)

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert len(result) == 1
        expected = datetime.fromtimestamp(epoch, tz=timezone.utc)
        assert result[0].created == expected
        assert result[0].created.tzinfo is not None


# ---------------------------------------------------------------------------
# invoice.payment_succeeded events
# ---------------------------------------------------------------------------


class TestInvoicePaymentSucceededEvents:
    def test_expanded_charge_object_yields_stripe_charge(self) -> None:
        """invoice.payment_succeeded with an expanded Charge object is returned."""
        expanded = _raw_charge_obj("ch_expanded", amount=5_000, currency="usd")
        event = _invoice_payment_event("evt_inv_001", charge_obj=expanded)
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([event], has_more=False)

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert len(result) == 1
        assert result[0].id == "ch_expanded"
        assert result[0].amount == 5_000

    def test_unexpanded_string_charge_id_is_skipped(self) -> None:
        """invoice.payment_succeeded where charge is a bare string ID is skipped."""
        event = _invoice_payment_event("evt_inv_str", charge_obj="ch_abc123")
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([event], has_more=False)

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert result == []

    def test_none_charge_is_skipped(self) -> None:
        """invoice.payment_succeeded where charge is None ($0 or credit note) is skipped."""
        event = _invoice_payment_event("evt_inv_none", charge_obj=None)
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([event], has_more=False)

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert result == []


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------


class TestCursorPagination:
    def test_two_pages_yields_all_charges_in_order(self) -> None:
        """Two pages of subscription events yield all extractable charges preserving order."""
        page1_events = [_charge_succeeded_event(f"ch_a{i}") for i in range(3)]
        for i, ev in enumerate(page1_events):
            ev.id = f"evt_a{i}"
        page2_events = [_charge_succeeded_event(f"ch_b{i}") for i in range(3)]
        for i, ev in enumerate(page2_events):
            ev.id = f"evt_b{i}"
        mock: MagicMock = MagicMock()
        mock.list_events.side_effect = [
            _page(page1_events, has_more=True),
            _page(page2_events, has_more=False),
        ]

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 3))

        assert len(result) == 6
        assert all(isinstance(c, StripeCharge) for c in result)
        assert [c.id for c in result] == [
            "ch_a0", "ch_a1", "ch_a2",
            "ch_b0", "ch_b1", "ch_b2",
        ]

    def test_cursor_advances_to_last_event_id_of_previous_page(self) -> None:
        """Second call receives starting_after equal to the last event id from page 1."""
        page1_events = [_charge_succeeded_event(f"ch_{i}") for i in range(3)]
        for i, ev in enumerate(page1_events):
            ev.id = f"evt_{i}"
        page2_events = [_charge_succeeded_event("ch_last")]
        page2_events[0].id = "evt_last"
        mock: MagicMock = MagicMock()
        mock.list_events.side_effect = [
            _page(page1_events, has_more=True),
            _page(page2_events, has_more=False),
        ]

        list(fetch_subscription_events(cast(StripeClient, mock), None, None, 3))

        first, second = mock.list_events.call_args_list
        assert first == call(
            starting_after=None,
            limit=3,
            types=["invoice.payment_succeeded", "charge.succeeded"],
            created_gte=None,
            created_lte=None,
        )
        assert second == call(
            starting_after="evt_2",
            limit=3,
            types=["invoice.payment_succeeded", "charge.succeeded"],
            created_gte=None,
            created_lte=None,
        )

    def test_makes_exactly_two_api_calls(self) -> None:
        """Loop exits after has_more=False on the second page; no extra calls."""
        page1_events = [_charge_succeeded_event(f"ch_{i}") for i in range(2)]
        for i, ev in enumerate(page1_events):
            ev.id = f"evt_{i}"
        page2_event = _charge_succeeded_event("ch_end")
        page2_event.id = "evt_end"
        mock: MagicMock = MagicMock()
        mock.list_events.side_effect = [
            _page(page1_events, has_more=True),
            _page([page2_event], has_more=False),
        ]

        list(fetch_subscription_events(cast(StripeClient, mock), None, None, 2))

        assert mock.list_events.call_count == 2

    def test_single_page_stops_after_one_call(self) -> None:
        """When has_more is False on the first page, exactly one API call is made."""
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page(
            [_charge_succeeded_event("ch_only")], has_more=False
        )

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert len(result) == 1
        assert mock.list_events.call_count == 1

    def test_mixed_page_skips_events_with_missing_charge_data(self) -> None:
        """Events without usable charge data are skipped; valid events are yielded."""
        # subscription charge.succeeded → yielded
        good = _charge_succeeded_event("ch_good")
        good.id = "evt_good"
        # non-subscription charge.succeeded → skipped
        no_inv = _charge_succeeded_event("ch_no_inv", invoice=None)
        no_inv.id = "evt_no_inv"
        # invoice event with bare string ID → skipped
        inv_str = _invoice_payment_event("evt_inv_str", charge_obj="ch_unexpanded")
        # invoice event with expanded charge → yielded
        inv_ok = _invoice_payment_event(
            "evt_inv_ok",
            charge_obj=_raw_charge_obj("ch_expanded"),
        )
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page(
            [good, no_inv, inv_str, inv_ok], has_more=False
        )

        result = list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        assert len(result) == 2
        assert {c.id for c in result} == {"ch_good", "ch_expanded"}


# ---------------------------------------------------------------------------
# Date bounds
# ---------------------------------------------------------------------------


class TestDateBounds:
    def test_date_bounds_forwarded_as_epoch_ints(self) -> None:
        """created_gte and created_lte datetime values are passed as epoch ints."""
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([], has_more=False)
        gte = datetime(2024, 1, 1, tzinfo=timezone.utc)
        lte = datetime(2024, 1, 31, tzinfo=timezone.utc)

        list(fetch_subscription_events(cast(StripeClient, mock), gte, lte, 10))

        mock.list_events.assert_called_once_with(
            starting_after=None,
            limit=10,
            types=["invoice.payment_succeeded", "charge.succeeded"],
            created_gte=int(gte.timestamp()),
            created_lte=int(lte.timestamp()),
        )

    def test_none_bounds_forwarded_as_none(self) -> None:
        """When no date range is given, None is passed for both epoch int params."""
        mock: MagicMock = MagicMock()
        mock.list_events.return_value = _page([], has_more=False)

        list(fetch_subscription_events(cast(StripeClient, mock), None, None, 10))

        mock.list_events.assert_called_once_with(
            starting_after=None,
            limit=10,
            types=["invoice.payment_succeeded", "charge.succeeded"],
            created_gte=None,
            created_lte=None,
        )
