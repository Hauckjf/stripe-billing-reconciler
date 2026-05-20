from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import stripe

from stripe_reconciler.client import StripeClient, _build_created_filter


class TestBuildCreatedFilter:
    def test_both_none_returns_none(self) -> None:
        assert _build_created_filter(None, None) is None

    def test_only_gte(self) -> None:
        result = _build_created_filter(1_700_000_000, None)
        assert result == {"gte": 1_700_000_000}

    def test_only_lte(self) -> None:
        result = _build_created_filter(None, 1_700_001_000)
        assert result == {"lte": 1_700_001_000}

    def test_both_bounds(self) -> None:
        result = _build_created_filter(1_700_000_000, 1_700_001_000)
        assert result == {"gte": 1_700_000_000, "lte": 1_700_001_000}


class TestStripeClientInit:
    def test_raises_on_empty_api_key(self) -> None:
        with pytest.raises(ValueError, match="api_key must not be empty"):
            StripeClient(api_key="")

    def test_sets_stripe_module_api_key(self) -> None:
        key = "sk_test_abc123"
        StripeClient(api_key=key)
        assert stripe.api_key == key

    def test_max_retries_stored(self) -> None:
        client = StripeClient(api_key="sk_test_abc", max_retries=3)
        assert client._max_retries == 3

    def test_default_max_retries_is_five(self) -> None:
        client = StripeClient(api_key="sk_test_abc")
        assert client._max_retries == 5


class TestListCharges:
    def test_happy_path_returns_list_object(self) -> None:
        client = StripeClient(api_key="sk_test_abc")
        mock_result: MagicMock = MagicMock()
        mock_result.data = [MagicMock()]
        mock_result.has_more = False

        with patch.object(stripe.Charge, "list", return_value=mock_result) as mock_list:
            result = client.list_charges(limit=10)

        mock_list.assert_called_once_with(limit=10)
        assert result is mock_result
        assert result.has_more is False

    def test_passes_cursor_and_date_range(self) -> None:
        client = StripeClient(api_key="sk_test_abc")

        with patch.object(stripe.Charge, "list", return_value=MagicMock()) as mock_list:
            client.list_charges(
                starting_after="ch_prev",
                limit=50,
                created_gte=1_700_000_000,
                created_lte=1_700_001_000,
            )

        mock_list.assert_called_once_with(
            limit=50,
            starting_after="ch_prev",
            created={"gte": 1_700_000_000, "lte": 1_700_001_000},
        )

    def test_no_created_key_when_bounds_absent(self) -> None:
        client = StripeClient(api_key="sk_test_abc")

        with patch.object(stripe.Charge, "list", return_value=MagicMock()) as mock_list:
            client.list_charges()

        assert "created" not in mock_list.call_args.kwargs

    def test_rate_limit_error_retries_and_reraises(self) -> None:
        client = StripeClient(api_key="sk_test_abc", max_retries=2)
        call_count = 0

        def raise_rate_limit(**_: Any) -> None:
            nonlocal call_count
            call_count += 1
            raise stripe.error.RateLimitError("rate limited")

        with patch("time.sleep"):  # suppress tenacity exponential wait
            with patch.object(stripe.Charge, "list", side_effect=raise_rate_limit):
                with pytest.raises(stripe.error.RateLimitError):
                    client.list_charges()

        assert call_count == 2  # initial attempt + 1 retry == max_retries

    def test_authentication_error_propagates_without_retry(self) -> None:
        client = StripeClient(api_key="sk_test_abc", max_retries=5)
        call_count = 0

        def raise_auth(**_: Any) -> None:
            nonlocal call_count
            call_count += 1
            raise stripe.error.AuthenticationError("bad key")

        with patch.object(stripe.Charge, "list", side_effect=raise_auth):
            with pytest.raises(stripe.error.AuthenticationError):
                client.list_charges()

        assert call_count == 1  # never retried


class TestListEvents:
    def test_happy_path_returns_list_object(self) -> None:
        client = StripeClient(api_key="sk_test_abc")
        mock_result: MagicMock = MagicMock()
        mock_result.data = [MagicMock()]
        mock_result.has_more = True

        with patch.object(stripe.Event, "list", return_value=mock_result) as mock_list:
            result = client.list_events(types=["charge.succeeded"], limit=25)

        mock_list.assert_called_once_with(limit=25, types=["charge.succeeded"])
        assert result is mock_result
        assert result.has_more is True

    def test_empty_types_list_omitted_from_params(self) -> None:
        client = StripeClient(api_key="sk_test_abc")

        with patch.object(stripe.Event, "list", return_value=MagicMock()) as mock_list:
            client.list_events(types=[], limit=10)

        assert "types" not in mock_list.call_args.kwargs

    def test_none_types_omitted_from_params(self) -> None:
        client = StripeClient(api_key="sk_test_abc")

        with patch.object(stripe.Event, "list", return_value=MagicMock()) as mock_list:
            client.list_events(types=None)

        assert "types" not in mock_list.call_args.kwargs

    def test_passes_cursor_and_date_range(self) -> None:
        client = StripeClient(api_key="sk_test_abc")

        with patch.object(stripe.Event, "list", return_value=MagicMock()) as mock_list:
            client.list_events(
                starting_after="evt_prev",
                limit=100,
                types=["invoice.payment_succeeded"],
                created_gte=1_700_000_000,
            )

        mock_list.assert_called_once_with(
            limit=100,
            starting_after="evt_prev",
            types=["invoice.payment_succeeded"],
            created={"gte": 1_700_000_000},
        )

    def test_api_connection_error_retries_and_reraises(self) -> None:
        client = StripeClient(api_key="sk_test_abc", max_retries=2)
        call_count = 0

        def raise_conn(**_: Any) -> None:
            nonlocal call_count
            call_count += 1
            raise stripe.error.APIConnectionError("timeout")

        with patch("time.sleep"):
            with patch.object(stripe.Event, "list", side_effect=raise_conn):
                with pytest.raises(stripe.error.APIConnectionError):
                    client.list_events()

        assert call_count == 2
