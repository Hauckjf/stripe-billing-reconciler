"""SQLite-backed local orders store for reconciliation cross-referencing."""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from stripe_reconciler.models import LocalOrder


class OrdersStore:
    """Manages a local SQLite `orders` table keyed by ``stripe_charge_id``.

    Typical lifecycle::

        store = OrdersStore(Path("orders.db"))
        store.load_from_csv(Path("orders.csv"))
        order = store.get_order_by_charge_id("ch_abc123")
        store.close()
    """

    _DDL_TABLE = """
        CREATE TABLE IF NOT EXISTS orders (
            order_id         TEXT,
            amount_cents     INTEGER NOT NULL,
            stripe_charge_id TEXT    NOT NULL,
            created_at       TEXT    NOT NULL
        )
    """
    _DDL_INDEX = """
        CREATE UNIQUE INDEX IF NOT EXISTS uix_orders_charge_id
        ON orders (stripe_charge_id)
    """

    def __init__(self, db_path: Path) -> None:
        self._conn: sqlite3.Connection = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(self._DDL_TABLE)
            self._conn.execute(self._DDL_INDEX)

    def load_from_csv(self, path: Path) -> int:
        """Bulk-insert orders from a CSV file that has a header row.

        Args:
            path: Path to the CSV file.  Expected columns (in any order):
                ``order_id``, ``amount_cents``, ``stripe_charge_id``, ``created_at``.

        Returns:
            Number of rows inserted.

        Raises:
            sqlite3.IntegrityError: If a ``stripe_charge_id`` already exists in the store.
        """
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = [
                (
                    row["order_id"] or None,
                    int(row["amount_cents"]),
                    row["stripe_charge_id"],
                    row["created_at"],
                )
                for row in reader
            ]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO orders (order_id, amount_cents, stripe_charge_id, created_at)"
                " VALUES (?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def load_from_sqlite(self, path: Path) -> int:
        """Import orders from an external SQLite database.

        ATTACHes *path* as ``src``, copies all rows from ``src.orders`` into
        the local store, then DETACHes.  DETACH runs in a ``finally`` block so
        the attachment is always released even when an ``IntegrityError`` is
        raised by a duplicate ``stripe_charge_id``.

        Args:
            path: Path to the source SQLite database file.

        Returns:
            Number of rows inserted.

        Raises:
            sqlite3.IntegrityError: If any imported ``stripe_charge_id`` collides
                with a row already in the local store.
        """
        self._conn.execute("ATTACH DATABASE ? AS src", (str(path),))
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO orders"
                    " (order_id, amount_cents, stripe_charge_id, created_at)"
                    " SELECT order_id, amount_cents, stripe_charge_id, created_at"
                    " FROM src.orders"
                )
                return cursor.rowcount
        finally:
            self._conn.execute("DETACH DATABASE src")

    def get_order_by_charge_id(self, charge_id: str) -> LocalOrder | None:
        """Return the order matching *charge_id*, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT order_id, amount_cents, stripe_charge_id, created_at"
            " FROM orders WHERE stripe_charge_id = ?",
            (charge_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_order(row)

    def get_all_orders(self) -> list[LocalOrder]:
        """Return every order currently in the store."""
        rows = self._conn.execute(
            "SELECT order_id, amount_cents, stripe_charge_id, created_at FROM orders"
        ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> LocalOrder:
        return LocalOrder(
            order_id=row["order_id"],
            amount_cents=row["amount_cents"],
            stripe_charge_id=row["stripe_charge_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
