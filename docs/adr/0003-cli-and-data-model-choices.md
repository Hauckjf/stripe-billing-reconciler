# ADR-0003: CLI framework and data model library

## Status

Accepted — 2026-05-21.

## Context

The reconciler exposes a single command (`reconcile`) with roughly eight flags: date-window bounds, an input CSV path, output format, verbosity, a dry-run toggle, and a database path override. It also models two domain objects that cross multiple architectural layers — `Order` (read from CSV) and `StripeCharge` (read from the API) — both of which must be validated before any reconciliation logic runs.

Two design decisions interact here:

1. **Which CLI framework to use** for flag parsing, `--help` generation, and shell-completion.
2. **Which data-model library to use** for the typed objects that flow between the fetcher, store, classifier, and formatter layers.

These decisions were made together because the correct choice in each category makes the other easier: a framework that understands Python type hints produces cleaner integration with a validation library that is also type-hint-native.

---

### CLI framework candidates

#### Option A — `argparse` (stdlib)

`argparse` ships with Python and has no runtime dependencies. It is, however, entirely imperative: each argument is registered with positional `add_argument` calls that duplicate information already present in the function signature and type hints. A flag like `--from-date` requires separate declarations of its name, `type=`, `metavar=`, `help=`, and `default=`, none of which are inferred from the surrounding code. For a tool with eight flags this is manageable, but the result is verbose, hard to keep in sync with the actual function signature, and produces weaker `--help` output (no automatic short/long alias grouping, no Enum rendering).

#### Option B — Click

Click is the dominant Python CLI framework. Its decorator model (`@click.command`, `@click.option`) is concise and well-understood. Click supports complex command groups with `pass_context` and result callbacks — useful when a parent command needs to post-process the exit code or output of every child command in a pipeline. Click also has a large ecosystem of extensions (Rich-Click for coloured help, Click-Repl for REPL mode, etc.).

The gap is that Click predates PEP 484 and does not read Python type annotations. Each `@click.option` must re-declare `type=click.DateTime(...)` or `type=click.Path(exists=True)` even when the underlying function already carries `from_date: datetime` and `csv: Path` in its signature. Passing a validated Pydantic model as a Click option type requires a custom `click.ParamType` subclass, adding glue code that is not needed by the alternative below.

#### Option C — Typer

Typer is a thin layer on top of Click that maps Python type annotations directly to CLI parameters. Given a function:

```python
def reconcile(
    from_date: Annotated[datetime, typer.Option(help="Start of window (ISO 8601)")],
    csv: Annotated[Path, typer.Option(exists=True, help="Orders CSV file")],
    format: Annotated[OutputFormat, typer.Option(help="json or table")] = OutputFormat.json,
) -> None:
```

Typer infers the Click option type from the annotation (`datetime` → `click.DateTime`, `Path` → `click.Path`, `OutputFormat` → `click.Choice`). The `--help` output is generated from the type and the `help=` string without any further boilerplate. Because Typer delegates to Click internally, its `typer.testing.CliRunner` is API-compatible with Click's test runner, and Click plugins still work.

---

### Data model candidates

#### Option A — stdlib `dataclasses`

`@dataclass` provides a typed container with generated `__init__`, `__repr__`, and `__eq__` at zero additional dependencies. Validation is not included: a field declared as `amount_cents: int` does not reject `amount_cents=-100` at construction time. Downstream code must guard against invalid values at every call site, or the tool must add a separate validation pass after construction. Serialising to JSON requires `dataclasses.asdict` followed by `json.dumps`, which does not respect custom field serialisers and cannot encode `datetime` or `Decimal` without a custom `default=` function.

#### Option B — `attrs`

`attrs` adds opt-in validators (`@amount_cents.validator`) and converters to the dataclass model. Validation logic is co-located with the field, which is better than separate guard clauses. The trade-off is that validators are imperative and do not compose across fields — a cross-field check (e.g. "refunded amount must not exceed original amount") requires a `__attrs_post_init__` hook, which is indistinguishable in style from what stdlib dataclasses would require. JSON serialisation still requires a manual step.

#### Option C — Pydantic v1

Pydantic v1 provides declarative validators, automatic coercion (string `"100"` → `int` 100), and `.json()` / `.dict()` serialisation. However, v1 has been in maintenance-only mode since Pydantic v2 reached GA in June 2023. Its internal implementation is pure Python, which makes validation noticeably slower for large datasets, and its `__fields__` introspection API is incompatible with v2.

#### Option D — Pydantic v2

Pydantic v2 rewrites the validation core in Rust, achieving roughly 5–17× faster model instantiation than v1 on benchmarks. The Python API is similar to v1 but adds `model_validator(mode="before")` for cross-field checks, `Field(ge=0)` for constraint declarations that mypy understands, and `model_dump_json()` for zero-glue JSON serialisation that handles `datetime`, `Decimal`, and nested models. The reconciler's JSON output mode calls `model_dump_json()` on a list of `Discrepancy` objects with no additional serialisation layer.

---

## Decision

### CLI: Typer

Use **Typer** as the CLI framework.

All command flags are declared as annotated function parameters. `OutputFormat` is a `str`-based `Enum`; Typer converts it to a `click.Choice` and renders valid values in `--help` automatically. `Path` annotations with `exists=True` are enforced before the command body executes, so the reconciler never opens a non-existent CSV file.

The accepted trade-off is that Typer's support for Click's `result_callback` on command groups is partial. A group-level callback that post-processes the combined output of multiple subcommands — for example, aggregating metrics across several `reconcile` runs invoked as subcommands of a parent — cannot be attached via Typer's decorator API without reaching into the underlying Click group object. This tool does not currently use multi-command pipelines, so the trade-off does not affect existing functionality. If a `reconcile-all` meta-command is added in the future, its result callback would need to be registered via `app.callback()` with `invoke_without_command=True` or by accessing `app.registered_commands`.

### Data model: Pydantic v2

Use **Pydantic v2** for all domain models (`Order`, `StripeCharge`, `Discrepancy`).

Constraint declarations at field level:

```python
class Order(BaseModel):
    order_id: str = Field(min_length=1)
    amount_cents: int = Field(ge=0)  # rejects negative at parse time
    stripe_charge_id: str = Field(min_length=1)
    created_at: datetime

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)
```

A `model_validator(mode="before")` on `Discrepancy` enforces the invariant that `ORDER_NOT_IN_STRIPE` records must carry a non-null `order_id` and a null `stripe_amount_cents`, catching logic errors in the classifier before they surface in the output:

```python
@model_validator(mode="before")
@classmethod
def _check_kind_fields(cls, data: dict) -> dict:
    if data.get("kind") == "ORDER_NOT_IN_STRIPE":
        assert data.get("stripe_amount_cents") is None, (
            "ORDER_NOT_IN_STRIPE must have stripe_amount_cents=None"
        )
    return data
```

The JSON formatter reduces to:

```python
def format_json(discrepancies: list[Discrepancy]) -> str:
    return (
        "[\n"
        + ",\n".join(d.model_dump_json(indent=2) for d in discrepancies)
        + "\n]"
    )
```

No custom `json.JSONEncoder` subclass is needed.

## Consequences

**Positive**

- **Single source of truth for CLI flags.** Flag name, type, default, and help string are declared once in the function signature. Renaming a flag or changing its type is a one-line edit; the old approach with Click decorators would require editing both the decorator and the function parameter independently.
- **Invalid inputs rejected before business logic runs.** Pydantic v2 raises `ValidationError` during CSV parsing if `amount_cents` is negative or non-integer, and during Stripe response parsing if `created` is missing. The reconciler never processes a structurally invalid record.
- **Zero-glue JSON output.** `model_dump_json()` handles `datetime` ISO serialisation and `Decimal` precision without a custom encoder, eliminating a class of serialisation bugs (e.g. `datetime` objects silently stringified with `str()` instead of `.isoformat()`).
- **mypy strict compatibility.** Pydantic v2 ships a mypy plugin (`pydantic.mypy`) that teaches mypy about `Field` constraints and `model_validator` signatures. Combined with Typer's annotation-driven API, the entire CLI-to-output path is statically typed without `Any` escapes.
- **Faster test suite.** Pydantic v2's Rust core instantiates models roughly 10× faster than v1 in microbenchmarks. With ~600 fixture rows in the test suite, instantiation overhead is negligible; at production scale (millions of charges) the speedup reduces total reconciliation wall time meaningfully.

**Negative / Trade-offs**

- **Typer `result_callback` limitation.** As noted under Decision, attaching a group-level result callback that post-processes child command output requires bypassing Typer's public API. This is not a current requirement but would need to be revisited before adding a multi-subcommand pipeline.
- **Pydantic v2 migration cost for adopters.** Any external code that imports `Order` or `Discrepancy` and was written against Pydantic v1's `.dict()` / `.json()` API will need to migrate to `.model_dump()` / `.model_dump_json()`. The tool is pre-1.0 and does not yet make stability guarantees on its internal models, so this is an acceptable break.
- **Runtime dependency size.** Adding Typer and Pydantic together brings in approximately 3 MB of installed files (including the Pydantic Rust extension). For a CLI tool distributed via `pip install`, this is a one-time cost paid at installation, not at runtime, and is substantially smaller than the Stripe Python SDK itself (~5 MB installed).
- **Typer pins to Click internals.** Typer wraps Click's group and command classes. A major Click release that changes internal APIs can break Typer until the Typer maintainers release a compatible version. The `pyproject.toml` pins both explicitly to avoid surprising breakage on `pip install --upgrade`.
