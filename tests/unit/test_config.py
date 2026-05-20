from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from stripe_reconciler.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_abc123")
    s = Settings()
    assert s.stripe_api_key.get_secret_value() == "sk_test_abc123"
    assert s.db_path == Path("./orders.db")
    assert s.stripe_page_size == 100
    assert s.max_retries == 5


def test_custom_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_xyz")
    monkeypatch.setenv("DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("STRIPE_PAGE_SIZE", "10")
    monkeypatch.setenv("MAX_RETRIES", "3")
    s = Settings()
    assert s.db_path == Path("/tmp/test.db")
    assert s.stripe_page_size == 10
    assert s.max_retries == 3


def test_get_settings_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_singleton")
    get_settings.cache_clear()
    try:
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------


def test_missing_stripe_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_page_size_too_low_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_xyz")
    monkeypatch.setenv("STRIPE_PAGE_SIZE", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_page_size_too_high_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_xyz")
    monkeypatch.setenv("STRIPE_PAGE_SIZE", "101")
    with pytest.raises(ValidationError):
        Settings()


def test_negative_max_retries_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_xyz")
    monkeypatch.setenv("MAX_RETRIES", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_stripe_api_key_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretStr must not leak the key value in repr/str."""
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_supersecret")
    s = Settings()
    assert "supersecret" not in repr(s)
    assert "supersecret" not in str(s.stripe_api_key)
