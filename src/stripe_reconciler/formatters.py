"""Output formatters: JSON, CSV, and rich table for Discrepancy lists."""

from __future__ import annotations

import csv
import io

from pydantic import TypeAdapter
from rich.console import Console
from rich.table import Table

from stripe_reconciler.models import Discrepancy

__all__ = ["to_json", "to_csv", "to_table"]

_ta: TypeAdapter[list[Discrepancy]] = TypeAdapter(list[Discrepancy])


def to_json(discrepancies: list[Discrepancy]) -> str:
    """Serialise *discrepancies* to pretty-printed JSON."""
    return _ta.dump_json(discrepancies, indent=2).decode()


def to_csv(discrepancies: list[Discrepancy]) -> str:
    """Serialise *discrepancies* to CSV (header + one row per discrepancy)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        ["kind", "charge_id", "order_id", "stripe_amount_cents", "order_amount_cents", "detail"]
    )
    for d in discrepancies:
        writer.writerow(
            [
                d.kind.value,
                d.charge_id if d.charge_id is not None else "",
                d.order_id if d.order_id is not None else "",
                "" if d.stripe_amount_cents is None else str(d.stripe_amount_cents),
                "" if d.order_amount_cents is None else str(d.order_amount_cents),
                d.detail,
            ]
        )
    return buf.getvalue()


def to_table(discrepancies: list[Discrepancy]) -> str:
    """Render *discrepancies* as a rich table string."""
    table = Table(show_header=True)
    table.add_column("Kind")
    table.add_column("Charge ID")
    table.add_column("Order ID")
    table.add_column("Stripe Amount (\u00a2)")
    table.add_column("Order Amount (\u00a2)")
    table.add_column("Detail")

    for d in discrepancies:
        table.add_row(
            d.kind.value,
            d.charge_id or "",
            d.order_id or "",
            "" if d.stripe_amount_cents is None else str(d.stripe_amount_cents),
            "" if d.order_amount_cents is None else str(d.order_amount_cents),
            d.detail,
        )

    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=200)
    console.print(table)
    return buf.getvalue()
