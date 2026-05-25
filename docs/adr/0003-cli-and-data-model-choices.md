# ADR-0003: CLI framework and data model library

## Status

Accepted — 2026-05-21. Supersedes a previous draft that selected Typer; see
"Reversal note" at the bottom.

## Context

The reconciler exposes a single command (`reconcile`) with seven flags:
`--from-date`, `--to-date`, `--db`, `--csv`, `--format`, `--output`, and
`--enrich-subscriptions`. It also models four domain objects that cross
multiple layers — `StripeCharge`, `StripeSubscription`, `LocalOrder`, and
`Discrepancy` (with `DiscrepancyKind` enum) — all of which must be validated
before any reconciliation logic runs.

Two design decisions interact:

1. **CLI framework** — flag parsing, `--help` generation, shell-completion.
2. **Data-model library** — typed objects flowing between fetcher, store,
   classifier, and formatter layers.

These decisions are coupled: a framework that understands Python type hints
integrates more cleanly with a validation library that is also type-hint
native.

### CLI framework candidates

#### Option A — `argparse` (stdlib)

Zero runtime dependencies. Entirely imperative: each argument is registered
with positional `add_argument` calls that duplicate information already in
the function signature. For a tool with seven flags this is verbose, hard to
keep in sync, and produces weaker `--help` output (no Enum rendering, no
automatic short/long aliases). Rejected — the verbosity cost is real and
this is not a constrained-dependency context (we already ship Pydantic and
tenacity).

#### Option B — Click

The dominant Python CLI framework. Decorator model (`@click.command`,
`@click.option`) is concise and well-understood. Click supports custom
parameter types via `click.ParamType` subclasses — used here to convert
`YYYY-MM-DD` strings to UTC-aware `datetime` objects via the `_IsoDate`
class. Click predates PEP 484 and does not infer parameter types from
function annotations, but this cost is one line per option and is paid once
per tool.

#### Option C — Typer

Thin layer over Click that maps Python type annotations directly to Click
options. `def reconcile(from_date: datetime, ...)` produces `--from-date` of
type `DateTime` automatically.

Trade-offs:

- Typer's parameter inference loses fidelity for custom types. The reconciler
  needs `YYYY-MM-DD` → UTC `datetime` (not the broader ISO-8601-with-time
  parsing Typer infers from `datetime`), which requires falling back to a
  manual `Annotated[..., typer.Option(...)]` declaration — eliminating most
  of Typer's value.
- Typer adds a dependency on top of Click that solves a problem this tool
  doesn't have at scale (7 flags, not 50+).
- Typer's testing helpers wrap Click's, which is an extra abstraction layer
  to learn.

### Data model candidates

#### Option A — stdlib `dataclasses`

Zero dependencies. No validation: `amount_cents: int` will accept `-100`
without complaint. Downstream code would need guards at every call site, or
a separate validation pass. JSON serialization requires `dataclasses.asdict`
+ a custom encoder for `datetime`/`Decimal`.

#### Option B — `attrs`

Adds opt-in field validators co-located with declarations. Cross-field
checks still require an `__attrs_post_init__` hook. JSON serialization is
still manual.

#### Option C — Pydantic v2

Rust-implemented validation core, ~5–17× faster than v1 on instantiation
benchmarks. Declarative constraints (`Field(ge=1, le=100)`) that mypy
understands. `model_dump_json()` handles `datetime`, `Decimal`, enums, and
nested models with zero glue code. Frozen-mode (`model_config =
ConfigDict(frozen=True)`) gives immutable value objects, which is what we
want for `StripeCharge`/`LocalOrder`/`Discrepancy` — they should never
mutate after construction.

## Decision

### CLI: Click

Use **Click** as the CLI framework. Custom parameter types (the `_IsoDate`
class in `cli.py`) handle the only non-standard parsing requirement
(`YYYY-MM-DD` → UTC `datetime`). The decorator model is concise enough for
seven flags without requiring Typer's annotation-inference layer.

### Data model: Pydantic v2

Use **Pydantic v2** for all domain models (`StripeCharge`, `StripeSubscription`,
`LocalOrder`, `Discrepancy`). All four are declared `frozen=True` —
immutable value objects. `DiscrepancyKind` is a `str`-based `Enum` so it
serializes cleanly to JSON without a custom encoder.

Configuration (`Settings`) uses `pydantic-settings.BaseSettings` to load env
vars with the same validation pipeline; `stripe_api_key` is `SecretStr` so
it cannot leak into logs.

## Consequences

### Positive

- **One validation pipeline.** Domain models, runtime config, and (via
  `model_dump_json`) the JSON output formatter all use the same Pydantic v2
  machinery. No second-layer hand-rolled validation.
- **Immutability by default.** `frozen=True` on every domain model rules
  out a whole class of bugs where a downstream caller mutates a `StripeCharge`
  after the classifier has already inspected it.
- **`--help` is generated.** Click renders the option table, defaults, and
  choices automatically; the help output is the single source of truth for
  what flags exist.

### Negative / Trade-offs

- **Click does not infer from annotations.** Each option re-declares `type=`
  even when the function signature already has the type. Mitigated by the
  small number of flags.
- **Pydantic v2 adds a dependency.** Acceptable — already needed for
  `pydantic-settings` and adds load-bearing capability (validation, JSON
  serialization, frozen models).

## Reversal note

An earlier version of this ADR selected **Typer**. That decision was reverted
during implementation because:

1. The only date format we accept is `YYYY-MM-DD` (UTC midnight). Typer's
   inference of `datetime` allows arbitrary ISO-8601 input including
   timezones, which expands the surface area we'd need to validate.
2. The dedicated `_IsoDate` custom parameter type in Click is short and
   self-documenting; the equivalent in Typer required `Annotated[...,
   typer.Option(parser=...)]` and a separate parser function, which is not
   simpler.
3. Typer is a thin Click wrapper. Once you reach for any non-trivial Click
   feature (custom parameter types, exit-code conventions) you are reading
   Click documentation anyway.

The deps in `pyproject.toml` reflect the current decision (`click`, no
`typer`). The Reversal note is preserved here for posterity.
