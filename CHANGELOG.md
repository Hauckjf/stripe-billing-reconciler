# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add cursor-based charge fetcher that pages through Stripe's Charges API with configurable page size and date-range filtering (`--from-date` / `--to-date`)
- Add event fetcher for Stripe Events API with cursor-based pagination and auto-resume via SQLite checkpoint table
- Add subscription fetcher that retrieves active and past-due subscriptions for optional discrepancy enrichment
- Add SQLite orders store with idempotent CSV import — re-running the same CSV never creates duplicate rows
- Add ATTACH-based SQLite source import so orders can be pulled directly from an existing SQLite database without an intermediate CSV export
- Add discrepancy classification engine with configurable tolerance window (`tolerance_cents`) — amount deltas within tolerance are silently accepted
- Add reconciliation engine that detects four discrepancy kinds: `AMOUNT_MISMATCH`, `CHARGE_NOT_IN_ORDERS`, `ORDER_NOT_IN_STRIPE`, and `DUPLICATE_CHARGE_ID`
- Add optional subscription enrichment (`--enrich-subscriptions`) that appends subscription status and ID to each discrepancy's detail field
- Add three output formatters: pretty-printed JSON, CSV with headers, and a Rich terminal table
- Add `stripe-reconcile reconcile` CLI command with flags for date range, database path, CSV import, output format, file output, and subscription enrichment
- Add typed domain models (`StripeCharge`, `StripeSubscription`, `LocalOrder`, `Discrepancy`, `DiscrepancyKind`) as immutable Pydantic models with full type annotations
- Add token-bucket rate limiter that caps outbound Stripe API calls to 100 req/s, preventing 429 errors on large reconciliation windows
- Add structured JSON logging with a per-run correlation ID attached to every log record for auditability
- Add mock mode via `STRIPE_MOCK_CHARGES_FILE` environment variable for offline development and testing without a live Stripe key
- Add pytest suite covering unit and integration paths with ≥85% line coverage enforced in GitHub Actions CI on every push
- Add mypy strict-mode type checking and ruff linting as required CI gates
- Add ADR 0001: SQLite for local orders store
- Add ADR 0002: cursor-based pagination strategy
- Add ADR 0003: CLI and data-model choices

[Unreleased]: https://github.com/Hauckjf/stripe-billing-reconciler/compare/v0.0.0...HEAD
