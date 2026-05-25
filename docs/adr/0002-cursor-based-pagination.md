# ADR-0002: Cursor-based pagination over Stripe list endpoints

## Status

Accepted — 2026-05-20.

## Context

The reconciler must iterate over every Stripe `Charge` and every relevant
subscription event (`invoice.payment_succeeded`, `charge.succeeded`) within a
configurable date range. Stripe's List APIs return at most 100 objects per
request. A production Stripe account can accumulate hundreds of thousands of
charges in a year, so iteration strategy is not academic.

Three retrieval strategies were considered:

### Option A — Fetch all records into memory

Issue a single unbounded query, accumulate every page in a Python list, then
iterate. Works for toy datasets and fails at scale: 1 000 000 charges ×
~400 bytes per object ≈ 400 MB of RAM before any reconciliation logic runs.
Also wasteful — if the caller only cares about the first divergence, it
should not require fetching the entire history.

### Option B — Offset pagination

Represent page position as a numeric offset (`offset=N`, `limit=100`). Stripe
does **not** expose an `offset` parameter on its list endpoints, so this
option is moot for Stripe specifically. Even if it did:

- Offset pagination reindexes the result set on each request. A charge
  created between page 1 and page 2 shifts every subsequent page, causing
  records to be skipped or visited twice.
- The cost of `OFFSET N` on the server scales linearly with N, which becomes
  a real problem on deep pages.

### Option C — Cursor-based pagination (`starting_after`)

Stripe exposes the last-returned object's ID as the cursor. The first request
returns up to 100 objects and a boolean `has_more`. If `has_more` is `True`,
the caller passes the ID of the last object as `starting_after` on the next
request, until `has_more` is `False`.

The cursor is anchored to a stable internal sort key, so concurrent inserts
do not shift already-visited pages.

## Decision

Use **cursor-based pagination** as the sole iteration strategy. The pattern
is encapsulated in three fetcher modules (`fetchers/charges.py`,
`fetchers/events.py`, `fetchers/subscriptions.py`), each implemented as a
Python generator that yields domain objects lazily:

```python
def fetch_all_charges(
    client: StripeClient,
    created_gte: datetime | None,
    created_lte: datetime | None,
    page_size: int,
) -> Iterator[StripeCharge]:
    cursor: str | None = None
    while True:
        page = client.list_charges(
            starting_after=cursor,
            limit=page_size,
            created_gte=int(created_gte.timestamp()) if created_gte else None,
            created_lte=int(created_lte.timestamp()) if created_lte else None,
        )
        for raw in page.data:
            yield StripeCharge(...)
        if not page.has_more:
            break
        cursor = page.data[-1].id
```

The generator pattern means the caller controls iteration. Memory stays
constant regardless of how many charges are reconciled — the full result set
is never buffered in process memory.

`page_size` is exposed as configuration (`stripe_page_size`, default 100,
constrained `ge=1, le=100` via Pydantic) rather than hard-coded, so a smaller
value can be used for low-volume testing without changing code.

Reference: [Stripe API — Pagination](https://stripe.com/docs/api/pagination)

## Consequences

### Positive

- **No silently-dropped records.** Because the cursor is an object ID tied
  to Stripe's internal sort, advancing the cursor always yields the next
  unseen page even when new charges arrive between fetches (concurrent
  inserts land on pages not yet fetched).
- **Constant memory.** Generator-based iteration means the reconciler can
  process accounts with millions of charges without loading them all into
  memory.
- **Same fetcher shape across endpoints.** Charges, events, and subscriptions
  all use the identical `while has_more` loop. The pattern is easy to
  recognize and verify across all three modules.

### Negative / Trade-offs

- **No resume on interruption.** This reconciler is intentionally stateless —
  if a run is killed mid-iteration, the next invocation starts from the
  beginning. Reconciliation runs are read-only (no destructive writes to
  Stripe), so re-fetching is safe and well-understood. A future variant
  could persist the cursor between runs, but the additional state machinery
  is not justified by the current single-CLI-invocation use case.
- **Cannot seek to an arbitrary position.** If a specific charge must be
  re-examined, the caller must either look it up by ID via the Stripe API
  directly, or scan from the beginning of the date window.
- **Stripe SDK pages internally too.** Calling `stripe.Charge.list()` with
  `auto_paging_iter()` would page automatically without explicit cursor
  management. We chose the explicit loop to keep the fetcher modules
  transparent and unit-testable without mocking the SDK iterator helper.
