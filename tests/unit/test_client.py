"""Unit tests for StripeClient — auth errors, rate-limit retries, backoff, and page-size forwarding."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import stripe

from stripe_reconciler.client import StripeClient


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity retries instantaneous in tests.

    Tenacity calls ``time.sleep`` via ``tenacity.nap`` between attempts. Without
    patching it, exponential-backoff retry tests take 6+ seconds each. Patching
    the global ``time.sleep`` is safe in this isolated test scope.
    """
    monkeypatch.setattr("time.sleep", lambda _: None)


@pytest.fixture
def client() -> StripeClient:
    """A StripeClient with a fake key and 3-attempt retry budget."""
    return StripeClient(api_key="sk_test_fake_key_for_unit_tests", max_retries=3)


_CHARGES_LIST = "stripe_reconciler.client.stripe.Charge.list"


def test_authentication_error_is_not_retried(client: StripeClient) -> None:
    """AuthenticationError must surface immediately — retrying a bad key is pointless."""
    with patch(_CHARGES_LIST, side_effect=stripe.error.AuthenticationError("bad key")) as mock_list:
        with pytest.raises(stripe.error.AuthenticationError):
            client.list_charges()
    mock_list.assert_called_once()


def test_rate_limit_error_retries_and_succeeds_on_third_attempt(client: StripeClient) -> None:
    """Two RateLimitErrors followed by a success: tenacity should reach the third call."""
    expected = MagicMock(name="charges_page")
    with patch(
        _CHARGES_LIST,
        side_effect=[
            stripe.error.RateLimitError("rate limited"),
            stripe.error.RateLimitError("rate limited again"),
            expected,
        ],
    ) as mock_list:
        result = client.list_charges()
    assert mock_list.call_count == 3
    assert result is expected


def test_api_connection_error_retries(client: StripeClient) -> None:
    """APIConnectionError is retryable; a single failure should not abort."""
    expected = MagicMock(name="charges_page")
    with patch(
        _CHARGES_LIST,
        side_effect=[stripe.error.APIConnectionError("network error"), expected],
    ) as mock_list:
        result = client.list_charges()
    assert mock_list.call_count == 2
    assert result is expected


def test_max_retries_exhausted_reraises(client: StripeClient) -> None:
    """After max_retries=3 RateLimitErrors in a row, the final error reraises."""
    with patch(
        _CHARGES_LIST,
        side_effect=[
            stripe.error.RateLimitError("rate limited"),
            stripe.error.RateLimitError("rate limited"),
            stripe.error.RateLimitError("rate limited"),
        ],
    ) as mock_list:
        with pytest.raises(stripe.error.RateLimitError):
            client.list_charges()
    assert mock_list.call_count == 3


def test_successful_call_returns_response_unchanged(client: StripeClient) -> None:
    """A clean call returns the Stripe ListObject as-is (no wrapping)."""
    expected = MagicMock(name="charges_page")
    with patch(_CHARGES_LIST, return_value=expected):
        result = client.list_charges()
    assert result is expected


def test_limit_forwarded_to_stripe(client: StripeClient) -> None:
    """The explicit ``limit`` kwarg is forwarded to stripe.Charge.list."""
    with patch(_CHARGES_LIST, return_value=MagicMock()) as mock_list:
        client.list_charges(limit=42)
    _, kwargs = mock_list.call_args
    assert kwargs.get("limit") == 42


def test_starting_after_forwarded_when_set(client: StripeClient) -> None:
    """The cursor ID is passed via starting_after when provided."""
    with patch(_CHARGES_LIST, return_value=MagicMock()) as mock_list:
        client.list_charges(starting_after="ch_lastseen")
    _, kwargs = mock_list.call_args
    assert kwargs.get("starting_after") == "ch_lastseen"


def test_starting_after_omitted_when_none(client: StripeClient) -> None:
    """starting_after=None must NOT appear in the Stripe call — Stripe rejects null cursors."""
    with patch(_CHARGES_LIST, return_value=MagicMock()) as mock_list:
        client.list_charges(starting_after=None)
    _, kwargs = mock_list.call_args
    assert "starting_after" not in kwargs


def test_empty_api_key_raises_at_construction() -> None:
    """Empty API key is a hard configuration error; surface at construction."""
    with pytest.raises(ValueError, match="api_key must not be empty"):
        StripeClient(api_key="")
