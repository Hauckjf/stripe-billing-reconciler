# ADR-0002: Cursor-based pagination over Stripe list endpoints

## Status

Accepted — 2026-05-20.

## Context

The reconciler must iterate over every Stripe `Charge` and subscription `Invoice` within a configurable date range. Stripe's List APIs return at most 100 objects per request. A production Stripe account accumulates millions of charges over time; a mid-size SaaS platform processing 50 000 transactions per month will have 600 000 charge objects after just one year.

Three retrieval strategies were considered:

### Option A — Fetch all records into memory

Issue a single unbounded query, accumulate every page in a Python list, then iterate. This is workable for toy datasets but fails in production: 1 000 000 charges × ~400 bytes per object = ~400 MB of in-process RAM before any reconciliation logic runs. It also forces the caller to handle pagination internally anyway, since the Stripe SDK still pages under the hood.

### Option B — Offset pagination

Represent page position as a numeric offset (`offset=N`, `limit=100`). Some REST APIs support this. Stripe does **not**: its list endpoints do not expose an `offset` parameter. More fundamentally, offset pagination on a large dataset is O(n) on the database server: to return page 10 000, the server must scan and discard the first 999 900 rows on every request. This compounds to serious performance degradation and increased risk of timeout on deep pages.

### Option C — Cursor-based pagination (`starting_after` / `ending_before`)

Stripe exposes a stable object ID as the cursor. The first request returns a page of up to 100 objects and a boolean `has_more`. If `has_more` is `true`, the caller passes the ID of the last object in the current page as `starting_after` in the next request. This continues until `has_more` is `false`.

Stripe sorts all list responses by `created` in descending order by default. The ID-based cursor is tied to that sort order, making each page boundary deterministic and stable across requests.

## Decision

Use **cursor-based pagination** (`starting_after=last_id`, `limit=100`) as the sole iteration strategy over all Stripe list endpoints in this tool.

The loop contract is:

```python
params = {"limit": 100, "created": {"gte": from_ts, "lte": to_ts}}
while True:
    page = stripe.Charge.list(**params)
    for charge in page.auto_paging_iter():  # SDK handles starting_after internally
        yield charge
    if not page.has_more:
        break
    params["starting_after"] = page.data[-1].id
```

`limit=100` is set explicitly because it is the maximum value Stripe accepts for any list endpoint. Omitting it defaults to `limit=10`, which would increase API call count by 10× and waste roughly 90 % of available throughput quota.

The tool persists the last-processed cursor (the charge ID) in a SQLite checkpoint table after each successfully processed page. An interrupted run resumes by reading this cursor and passing it as `starting_after`, skipping all previously processed objects without re-fetching them.

Reference: [Stripe API — Pagination](https://stripe.com/docs/api/pagination)

## Consequences

**Positive**

- **No duplicate pages.** Because the cursor is an opaque object ID tied to Stripe's internal sort index, advancing the cursor always yields the next unseen page. Contrast with offset pagination where a new insert at page 1 would shift every subsequent page, causing objects to be visited twice or skipped.
- **Resilient to concurrent inserts.** New charges created while the reconciler is running appear only on pages not yet fetched (they land at the head of the descending-`created` list). Pages already consumed remain unaffected.
- **Deterministic ordering.** Stripe guarantees descending `created` order for all list endpoints. Combined with the stable ID cursor, each run over the same date range visits objects in the same sequence, which simplifies debugging and audit comparison between runs.
- **Checkpoint-resumable.** Persisting `last_cursor` in SQLite after each page means a crashed or rate-limited run resumes from the last committed page rather than restarting from scratch. This is essential for accounts with millions of charges where a full scan takes minutes.
- **Rate-limit budget efficiency.** `limit=100` minimises the number of API requests needed to cover a date range, leaving more of the 100 req/s Stripe budget for the token-bucket throttler to allocate to retries and metadata lookups.

**Negative / Trade-offs**

- **Cannot seek to an arbitrary position by index.** If a specific charge must be re-examined, the caller must either store its ID directly or scan from the beginning. In practice the checkpoint table stores individual charge IDs for matched/unmatched records, so point-lookup is always by ID, never by offset.
- **Descending order requires reversing if ascending output is desired.** The reconciler collects all results then sorts by `created ASC` before writing the JSON report. This adds an in-memory sort step, but since the report is bounded by the requested date range (not the full account history), the memory cost is acceptable.
- **SDK wraps cursor details.** `stripe.Charge.list().auto_paging_iter()` handles `starting_after` automatically. The checkpoint integration must tap into the raw page objects rather than the iterator to capture the cursor ID, which adds a small amount of SDK-coupling. This is documented in the fetcher module.
