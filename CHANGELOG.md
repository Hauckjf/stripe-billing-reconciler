# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Cursor-based charge fetcher (`fetchers/charges.py`) that pages through Stripe's Charges API via `starting_after`, with configurable page size and `created_gte`/`created_lte` date-range filtering
- Subscription-event fetcher (`fetchers/events.py`) for `invoice.payment_succeeded` and `charge.succeeded` events, with defensive `_charge_from_event` parsing that returns `None` on missing or expandable-but-unexpanded charge references
- Subscriptions fetcher (`fetchers/subscriptions.py`) used by the `--enrich-subscriptions` opt-in path
- `StripeClient` wrapper around the Stripe SDK with `tenacity`-based retry (exponential backoff, multiplier=2, ceiling=60s) on `RateLimitError` and `APIConnectionError`; `AuthenticationError` is excluded from retry
- SQLite orders store (`store.py`) with `UNIQUE INDEX` on `stripe_charge_id` — re-importing the same CSV raises `IntegrityError` instead of silently doubling local state
- `ATTACH DATABASE`-based SQLite source import so orders can be pulled directly from an existing SQLite database without an intermediate CSV export
- `DiscrepancyClassifier` (`classifier.py`) — pure-domain classifier with configurable `tolerance_cents` window; no I/O, testable in isolation
- Reconciliation engine (`reconciler.py`) that detects four discrepancy kinds: `AMOUNT_MISMATCH`, `CHARGE_NOT_IN_ORDERS`, `ORDER_NOT_IN_STRIPE`, and `DUPLICATE_CHARGE_ID`
- Optional subscription enrichment via `--enrich-subscriptions`: appends subscription ID and status to the `detail` field of relevant discrepancies, without changing the `Discrepancy` schema
- Three output formatters: pretty-printed JSON, CSV with headers, and a Rich terminal table
- `stripe-reconcile reconcile` CLI command with flags `--from-date`, `--to-date`, `--db`, `--csv`, `--format`, `--output`, `--enrich-subscriptions`. Exit code is `0` on a clean run, `1` when at least one discrepancy is detected
- Typed domain models (`StripeCharge`, `StripeSubscription`, `LocalOrder`, `Discrepancy`, `DiscrepancyKind`) as immutable Pydantic v2 models (`frozen=True`)
- Configuration via `pydantic-settings.BaseSettings` — `stripe_api_key` is `SecretStr` so it cannot leak into logs or `repr()`. `get_settings()` is `@lru_cache(maxsize=1)` for a process-wide singleton
- Mock mode via `STRIPE_MOCK_CHARGES_FILE` environment variable for offline development and testing without a live Stripe key
- Pytest suite covering unit and integration paths (`tests/unit/`, `tests/integration/`) with a `--cov-fail-under=85` gate configured in `pyproject.toml`
- ADR-0001: SQLite for the local orders store
- ADR-0002: cursor-based pagination over Stripe list endpoints
- ADR-0003: CLI framework (Click) and data-model library (Pydantic v2)

[Unreleased]: https://github.com/Hauckjf/stripe-billing-reconciler/compare/v0.0.0...HEAD
