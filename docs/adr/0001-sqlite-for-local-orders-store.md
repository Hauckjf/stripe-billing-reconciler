# ADR-0001: SQLite for the local orders store

## Status

Accepted — 2026-05-20.

## Context

The reconciler cross-references Stripe charges against an internal orders
table. That table needs to live *somewhere* the CLI can read. Three properties
are non-negotiable for the use case:

- **Zero infrastructure.** The tool runs from a developer's laptop, a CI runner,
  or a cron container. Requiring a PostgreSQL/MySQL server to "do a
  reconciliation" forces every consumer to provision and credential a database
  before they can use the tool at all. That is a non-starter for a small
  open-source utility.
- **Auditable on-disk format.** When a finance team reviews a reconciliation
  report and asks "what was in the orders table when this ran?", the answer
  should be a single file they can copy aside, attach to a ticket, or open
  with the standard `sqlite3` CLI for ad-hoc inspection.
- **Idempotent CSV import.** The primary input is a CSV exported from the
  consumer's own billing system. Reimporting the same CSV must not silently
  double the local state.

The candidate options were:

### Option A — In-memory only (no persistence)

Read the CSV into a Python `dict` at run-time, reconcile, discard. Simplest
possible. Rejected because:

- No way to inspect the orders snapshot after the fact (auditability)
- Re-running a reconciliation forces re-reading the entire CSV every time
- Doesn't support the use case where orders are already in an existing
  SQLite file from another tool (see `load_from_sqlite` ATTACH path)

### Option B — PostgreSQL / MySQL

Production-grade RDBMS. Rejected because:

- Forces every consumer to provision infrastructure before the tool is useful
- Adds connection pooling, network, authentication concerns to a CLI that
  should be drop-in
- Solves a scale problem (multi-writer, replication) that does not exist
  here — a single-process CLI is the only writer

### Option C — SQLite (chosen)

Embedded, file-backed, single-file, zero-config. The Python stdlib ships the
`sqlite3` driver, so there is no extra dependency. The store fits in one
Python module (`store.py`) and one schema DDL block.

## Decision

Use **SQLite** as the local orders store, with the following constraints
expressed in `_DDL_TABLE` and `_DDL_INDEX`:

```sql
CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT,
    amount_cents     INTEGER NOT NULL,
    stripe_charge_id TEXT    NOT NULL,
    created_at       TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uix_orders_charge_id
    ON orders (stripe_charge_id);
```

`order_id` is nullable because some legacy CSV exports leave it blank
(matching is via `stripe_charge_id`). `amount_cents` is `NOT NULL` because an
order without an amount is unreconcilable. The `UNIQUE INDEX` on
`stripe_charge_id` is the load-bearing piece: it makes CSV re-imports fail
loudly (`sqlite3.IntegrityError`) instead of doubling local state.

## Consequences

### Positive

- **No infrastructure.** The default `--db ./orders.db` works on any machine
  with Python 3.11+.
- **Auditable.** The DB file can be archived alongside the reconciliation
  report. A reviewer opens it with `sqlite3 orders.db "SELECT * FROM orders"`
  to see exactly what was matched against.
- **Idempotent imports by construction.** The UNIQUE INDEX makes "re-running
  the same CSV produces the same DB state" a contract enforced by SQLite, not
  by application code.
- **External-DB import without conversion.** `OrdersStore.load_from_sqlite`
  uses `ATTACH DATABASE … AS src` to pull rows directly from an existing
  SQLite database. Consumers who already store orders in SQLite skip the CSV
  step entirely.

### Negative / Trade-offs

- **Single-writer only.** SQLite handles concurrent readers but not concurrent
  writers across processes. The reconciler is a single-process CLI so this is
  not a current limitation, but a future "watch mode" that ran multiple
  reconcile jobs in parallel would need a different store.
- **No network access.** Cannot be read by another machine without copying
  the file. For a CLI tool this is the desired behavior; for a service it
  would be wrong.
- **`TEXT` for timestamps.** SQLite has no native datetime type; the store
  serializes `created_at` as ISO-8601 TEXT and parses on read
  (`datetime.fromisoformat`). The cost is one parse per row at read time; the
  benefit is portability (the file can be inspected without the reconciler's
  Python code).
