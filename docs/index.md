---
layout: page
title: Stripe Billing Reconciler
---

Reconcile Stripe charges and subscriptions against your internal orders table — cursor-paginated, idempotent, rate-limit-aware, and auditable.

[![asciicast](https://asciinema.org/a/718261.svg)](https://asciinema.org/a/718261)

## Links

- [Installation](https://github.com/Hauckjf/stripe-billing-reconciler#installation)
- [Usage](https://github.com/Hauckjf/stripe-billing-reconciler#usage)
- [Architecture](https://github.com/Hauckjf/stripe-billing-reconciler#architecture)

## Architecture Decision Records

- [ADR 0001 — SQLite for local orders store](adr/0001-sqlite-for-local-orders-store.md)
- [ADR 0002 — Cursor-based pagination](adr/0002-cursor-based-pagination.md)
- [ADR 0003 — CLI and data model choices](adr/0003-cli-and-data-model-choices.md)
