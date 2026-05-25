"""CLI entrypoint for stripe-billing-reconciler."""
from __future__ import annotations

import itertools
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import click

from stripe_reconciler.client import StripeClient
from stripe_reconciler.config import Settings
from stripe_reconciler.fetchers.charges import fetch_all_charges
from stripe_reconciler.fetchers.events import fetch_subscription_events
from stripe_reconciler.fetchers.subscriptions import fetch_subscriptions
from stripe_reconciler.formatters import to_csv, to_json, to_table
from stripe_reconciler.models import StripeCharge, StripeSubscription
from stripe_reconciler.reconciler import reconcile as _run_reconcile
from stripe_reconciler.store import OrdersStore


class _IsoDate(click.ParamType):
    """Click parameter type: YYYY-MM-DD string → UTC-aware datetime."""

    name = "DATE"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> Any:
        if value is None or isinstance(value, datetime):
            return value
        try:
            d = date.fromisoformat(str(value))
        except ValueError:
            self.fail(f"expected YYYY-MM-DD, got {value!r}", param, ctx)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


_ISO_DATE = _IsoDate()


@click.group()
def cli() -> None:
    """Stripe Billing Reconciler — cross-reference Stripe charges against your orders table."""


@cli.command()
@click.option(
    "--from-date",
    "from_date",
    default=None,
    type=_ISO_DATE,
    metavar="YYYY-MM-DD",
    help="Inclusive start date for the reconciliation window (UTC midnight).",
)
@click.option(
    "--to-date",
    "to_date",
    default=None,
    type=_ISO_DATE,
    metavar="YYYY-MM-DD",
    help="Inclusive end date for the reconciliation window (UTC midnight).",
)
@click.option(
    "--db",
    "db_path",
    default=Path("./orders.db"),
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the local SQLite orders database.",
)
@click.option(
    "--csv",
    "csv_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "CSV file to import into the orders database before reconciling. "
        "The database at --db must not already contain rows (fresh DB only)."
    ),
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv", "table"], case_sensitive=False),
    default="table",
    show_default=True,
    help="Output format for the discrepancy report.",
)
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the report to this file. Defaults to stdout.",
)
@click.option(
    "--enrich-subscriptions",
    "enrich_subscriptions",
    is_flag=True,
    default=False,
    help=(
        "Fetch all Stripe subscriptions and append subscription context "
        "(ID and status) to AMOUNT_MISMATCH and CHARGE_NOT_IN_ORDERS "
        "discrepancies whose charge carries a subscription_id in its metadata."
    ),
)
def reconcile(
    from_date: datetime | None,
    to_date: datetime | None,
    db_path: Path,
    csv_path: Path | None,
    output_format: str,
    output_path: Path | None,
    enrich_subscriptions: bool,
) -> None:
    """Fetch Stripe charges and events, cross-reference against local orders, report discrepancies.

    Exit code 0 — clean run, no discrepancies found.
    Exit code 1 — at least one discrepancy was detected.
    """
    try:
        settings = Settings(db_path=db_path)
    except Exception as exc:
        raise click.ClickException(
            f"Configuration error: {exc}\n"
            "Ensure STRIPE_API_KEY is set in your environment or a .env file."
        ) from exc

    store = OrdersStore(db_path)

    if csv_path is not None:
        # Mutual exclusion: refuse to import CSV on top of an already-populated DB.
        existing = store.get_all_orders()
        if existing:
            store.close()
            raise click.UsageError(
                f"--csv {csv_path} conflicts with existing rows in {db_path}. "
                "Remove the database or point --db to a fresh path."
            )
        try:
            store.load_from_csv(csv_path)
        except Exception as exc:
            store.close()
            raise click.ClickException(f"Failed to import {csv_path}: {exc}") from exc

    client = StripeClient(
        api_key=settings.stripe_api_key.get_secret_value(),
        max_retries=settings.max_retries,
    )

    try:
        seen: set[str] = set()
        charges: list[StripeCharge] = []
        for charge in itertools.chain(
            fetch_all_charges(client, from_date, to_date, settings.stripe_page_size),
            fetch_subscription_events(client, from_date, to_date, settings.stripe_page_size),
        ):
            if charge.id not in seen:
                seen.add(charge.id)
                charges.append(charge)
    except Exception as exc:
        store.close()
        raise click.ClickException(f"Stripe API error: {exc}") from exc

    subscriptions: list[StripeSubscription] | None = None
    if enrich_subscriptions:
        try:
            subscriptions = list(fetch_subscriptions(client, settings.stripe_page_size))
        except Exception as exc:
            store.close()
            raise click.ClickException(
                f"Stripe API error fetching subscriptions: {exc}"
            ) from exc

    discrepancies = _run_reconcile(charges, store, subscriptions=subscriptions)
    store.close()

    formatters = {"json": to_json, "csv": to_csv, "table": to_table}
    report = formatters[output_format](discrepancies)

    if output_path is not None:
        try:
            output_path.write_text(report, encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Cannot write to {output_path}: {exc}") from exc
    else:
        click.echo(report, nl=False)

    if discrepancies:
        sys.exit(1)


def main() -> None:
    """Console-script entry point declared in pyproject.toml.

    Resolves to ``stripe-reconcile`` after ``pip install``; invokes the Click
    group, which dispatches to ``reconcile`` (or any future subcommand).
    """
    cli()
