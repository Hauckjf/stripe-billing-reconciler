"""Unit tests for StripeClient — auth errors, rate-limit retries, backoff, and page-size forwarding."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import stripe

from stripe_reconciler.client import StripeClient
from stripe_reconciler.config import Config


@pytest.fixture()
def config() -> Config:
    return Config(stripe_api_key="sk_test_fake_key_for_unit_tests", stripe_page_size=25)


@pytest.fixture()
def client(config: Config) -> StripeClient:
    return StripeClient(config)


_CHARGES_LIST = "stripe_reconciler.client.stripe.Charge.list"


def test_authentication_error_is_not_retried(client: StripeClient) -> None:
    """AuthenticationError must surface immediately — retrying a bad key is pointless."""
    with patch(_CHARGES_LIST, side_effect=stripe.AuthenticationError("bad key")) as mock_list:
        with pytest.raises(stripe.AuthenticationError):
            client.list_charges()
    mock_list.assert_called_once()


def test_rate_limit_error_retries_and_succeeds_on_third_attempt(client: StripeClient) -> None:
    expected = MagicMock(name="charges_page")
    with patch(
        _CHARGES_LIST,
        side_effect=[
            stripe.RateLimitError("rate limited"),
            stripe.RateLimitError("rate limited again"),
            expected,
        ],
    ) as mock_list:
        result = client.list_charges()
    assert mock_list.call_count == 3
    assert result is expected


def test_api_connection_error_retries_with_backoff(client: StripeClient) -> None:
    expected = MagicMock(name="charges_page")
    with patch(
        _CHARGES_LIST,
        side_effect=[stripe.APIConnectionError("network error"), expected],
    ):
        with patch("stripe_reconciler.client.time.sleep") as mock_sleep:
            result = client.list_charges()
    mock_sleep.assert_called()
    assert result is expected


def test_successful_call_returns_response_unchanged(client: StripeClient) -> None:
    expected = MagicMock(name="charges_page")
    with patch(_CHARGES_LIST, return_value=expected):
        result = client.list_charges()
    assert result is expected


def test_stripe_page_size_forwarded_as_limit(client: StripeClient, config: Config) -> None:
    with patch(_CHARGES_LIST, return_value=MagicMock()) as mock_list:
        client.list_charges()
    _, kwargs = mock_list.call_args
    assert kwargs.get("limit") == config.stripe_page_size
