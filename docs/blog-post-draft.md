---
title: "Stripe Billing Reconciliation: the trade-offs that matter in production"
status: draft
published: false
category: devtools
---

# Stripe Billing Reconciliation: the trade-offs that matter in production

> **Status: draft** — not yet published. Post link will be wired manually after publication on [portfolio.fabiodiashauck.com.br/blog](https://portfolio.fabiodiashauck.com.br/blog).

---

## 1. The billing discrepancy problem — why Stripe's event log and the app DB drift over time

- Stripe's event log and the application database have no shared transaction boundary. A crash between "write order row" and "call Stripe" leaves a local record with no corresponding charge; a webhook that arrives after an endpoint outage creates the inverse: a Stripe charge that never maps to an order. Neither system surfaces the mismatch — it silently accumulates until a monthly close or an audit triggers the investigation.
- Practical drift scenarios that appear in production: (a) partial refunds applied via the Stripe Dashboard or support tooling that never trigger a compensating update in the orders table; (b) subscription renewal charges billed through `invoice.payment_succeeded` that land as `Charge` objects without a corresponding order row in the application DB; (c) manual charges created directly in the Dashboard by a support agent that bypass the order creation flow entirely.
- The operational consequence is twofold: unreported revenue (charges in Stripe not reflected in the orders table) and potential double-billing risk (orders in the DB referencing charge IDs that were never settled). A reconciler that runs nightly — or as a CI billing health gate — closes the detection gap before discrepancies compound across billing cycles.

---

## 2. Cursor-based pagination — why offset fails for reconciliation at scale

- Stripe's List APIs expose `starting_after=<last_object_id>` as the sole iteration mechanism — there is no `offset` parameter. Even if offset were available, it would be structurally broken for reconciliation: a new charge inserted at the head of the descending-`created` list shifts every subsequent page by one row, causing records on adjacent page boundaries to be visited twice or skipped entirely. Cursor-based pagination is immune because the cursor is an opaque object ID tied to Stripe's internal sort index, not a positional count.
- The loop contract implemented in this tool: request the first page with `limit=100` (the maximum Stripe accepts) and `created >= from_ts, <= to_ts`; on each response check `page.has_more`; if `True`, pass `page.data[-1].id` as `starting_after` for the next request; persist this cursor to the SQLite checkpoint table after each successfully processed page. An interrupted run — due to a rate-limit 429, a network timeout, or a SIGTERM from CI — resumes by reading the stored cursor and issuing the next request mid-stream. On an account with one million charges, a resumed run skips all previously processed pages without re-fetching a single object.
- Setting `limit=100` instead of the SDK default of `limit=10` reduces API call count by 10× for the same date window, leaving 90% more of Stripe's 100 req/s quota for the token-bucket rate-limiter to allocate to retries and subscription metadata lookups. Omitting the explicit limit is a silent 10× performance regression that only manifests at scale.

---

## 3. Classifying discrepancies — the four types and their operational implications

- **`AMOUNT_MISMATCH`** — a charge exists in both Stripe and the local orders table but `abs(stripe_amount - order_amount_cents) > tolerance_cents`. Common cause: multi-currency conversion where Stripe and the local ledger apply different rounding modes when converting fractional cents. Operational implication: requires a manual finance review and potentially a corrective credit note; severity scales with the absolute signed delta (logged as `+N` or `-N` cents in the discrepancy detail).
- **`CHARGE_NOT_IN_ORDERS`** — Stripe returned a charge with no matching `stripe_charge_id` row in the orders table. Common causes: a manual charge created via the Dashboard, a webhook that fired after the application crashed mid-transaction, or a test-mode charge that leaked into a shared database state. Operational implication: potential unreported revenue — the customer was billed but the application has no record of fulfilling the corresponding order.
- **`ORDER_NOT_IN_STRIPE`** — the orders table references a `stripe_charge_id` absent from the Stripe API response for the given date window. Common causes: the charge was created outside the reconciled window, the Stripe API call failed silently and the charge was never created, or the charge was subsequently deleted (voided). Operational implication: the customer may have an unfulfilled order or the application accepted an order without confirming payment — an incomplete saga.
- **`DUPLICATE_CHARGE_ID`** — the same `stripe_charge_id` appears on more than one local order row; detected by `reconciler.detect_duplicates` before the join step so it does not contaminate the match results. Operational implication: a data integrity violation in the orders table — one charge is financing multiple order rows; investigate the order creation flow for race conditions or retry logic that writes without a unique-constraint check on `stripe_charge_id`.

---

## 4. SQLite for a CLI tool — the ADR-0001 reasoning condensed

- A CLI tool that runs on a developer's machine or in a CI container needs zero-infrastructure persistence: no Postgres server to provision, no connection string to configure, no migration runner to invoke before the first run. SQLite meets all three constraints with a single file at a configurable path (`--db-path`, defaulting to `reconciler.db` in the current working directory).
- Two tables do the work: `reconciler_cursors` stores the last processed `starting_after` cursor keyed by `(from_date, to_date)` so interrupted runs resume from the last committed page; `local_orders` is populated once from the input CSV via `--csv` and reused across partial runs, avoiding repeated CSV parsing on resume. SQLite's single-writer model serialises concurrent access at the OS file-lock level — a second `reconcile` invocation from a parallel CI job blocks until the first commits or rolls back, preventing checkpoint corruption without any application-level locking code.
- Trade-off accepted: the file lock means the reconciler cannot scale horizontally across parallel workers without partitioning the date range into non-overlapping shards and giving each a separate `--db-path`. For the target use case — nightly CI runs and ad-hoc finance audits by a single operator — this constraint never binds. A future distributed variant would replace the SQLite checkpoint table with a shared key-value store (Redis, DynamoDB), leaving the reconciliation and classification logic unchanged.

---

## 5. Exit-code contract for CI integration — using the reconciler as a billing health gate

- The CLI exits `0` when reconciliation completes with zero discrepancies and `1` when at least one discrepancy of any kind is found. This follows the Unix convention for "something requires attention" and integrates without glue code into `|| exit 1` chains, `Makefile` targets, and GitHub Actions `continue-on-error: false` steps.
- A minimal GitHub Actions billing health gate that runs nightly and archives the JSON report as an audit artifact:
  ```yaml
  - name: Billing reconciliation gate
    env:
      STRIPE_API_KEY: ${{ secrets.STRIPE_RECONCILE_KEY }}
    run: |
      stripe-reconcile reconcile \
        --from-date $(date -d "yesterday" +%Y-%m-%d) \
        --to-date   $(date +%Y-%m-%d) \
        --csv       orders/yesterday.csv \
        --format    json \
        --output    reconciliation-report.json
  - uses: actions/upload-artifact@v4
    if: always()
    with:
      name: reconciliation-report-${{ github.run_id }}
      path: reconciliation-report.json
  ```
  When the exit code is `1` the workflow step fails, the on-call engineer receives the default Actions failure notification, and the uploaded artifact contains the full discrepancy payload for triage. The `if: always()` on the upload ensures the report is preserved even when the gate fails.
- The Stripe restricted API key stored in CI secrets should carry **read-only** access scoped to **Charges** and **Subscriptions** only (Dashboard → Developers → Restricted keys). Granting write permissions to a key stored in CI secrets is unnecessary blast-radius expansion for a read-only audit tool — if the secret leaks, the attacker can enumerate billing data but cannot initiate charges or issue refunds.

---

## 6. Key takeaways and next steps (webhooks as real-time complement)

- **The reconciler solves the batch detection problem**: it answers "are our billing records consistent across a given date window?" with an auditable, CI-gateable JSON artifact. It surfaces discrepancies after the fact; it does not prevent them from occurring. The value is in catching drift before it reaches the monthly close, when corrective action is still cheap.
- **Webhooks are the real-time complement**: subscribing to `charge.succeeded`, `charge.refunded`, and `invoice.payment_succeeded` and writing idempotently to the orders table (unique constraint on `stripe_charge_id`) eliminates the root cause of most `ORDER_NOT_IN_STRIPE` and `CHARGE_NOT_IN_ORDERS` discrepancies. The reconciler then becomes a safety net for the tail cases — webhook delivery failures, handler crashes, support-agent Dashboard actions — rather than the primary detection mechanism.
- **Concrete next steps for production hardening**: (a) add `--severity-threshold` to exit `0` for `AMOUNT_MISMATCH` deltas below a configurable rounding tolerance (e.g. ±$0.50) while still failing for any missing-charge record regardless of amount; (b) emit an OpenTelemetry span per reconciliation run (total charges scanned, discrepancy counts by kind, wall time) to a metrics backend for week-over-week trend analysis; (c) extend `DiscrepancyKind` with `REFUND_NOT_REFLECTED` — charges where `amount_refunded > 0` in the Stripe response but whose local order row still records the original `amount_cents` — covering the partial-refund drift scenario described in section 1.
