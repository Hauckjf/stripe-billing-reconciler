"""Behavioural tests for OrdersStore."""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stripe_reconciler.store import OrdersStore

_CREATED_AT = "2024-01-15T10:30:00+00:00"
_CHARGE_ID = "ch_test_abc123"
_ORDER_ID = "ord_001"
_AMOUNT_CENTS = 9900


@pytest.fixture()
def store(tmp_path: Path) -> Generator[OrdersStore, None, None]:
    s = OrdersStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,amount_cents,stripe_charge_id,created_at\n"
        f"{_ORDER_ID},{_AMOUNT_CENTS},{_CHARGE_ID},{_CREATED_AT}\n",
        encoding="utf-8",
    )
    return csv_path


class TestSchemaInit:
    def test_fresh_store_has_empty_orders_table(self, tmp_path: Path) -> None:
        s = OrdersStore(tmp_path / "init.db")
        orders = s.get_all_orders()
        s.close()
        assert orders == []

    def test_reinitialising_same_db_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "reinit.db"
        s1 = OrdersStore(db_path)
        s1.close()
        s2 = OrdersStore(db_path)
        s2.close()


class TestLoadFromCsv:
    def test_returns_inserted_row_count(self, store: OrdersStore, sample_csv: Path) -> None:
        count = store.load_from_csv(sample_csv)
        assert count == 1

    def test_round_trip_correct_fields_via_charge_id(self, store: OrdersStore, sample_csv: Path) -> None:
        store.load_from_csv(sample_csv)
        order = store.get_order_by_charge_id(_CHARGE_ID)

        assert order is not None
        assert order.order_id == _ORDER_ID
        assert order.amount_cents == _AMOUNT_CENTS
        assert order.stripe_charge_id == _CHARGE_ID
        assert isinstance(order.created_at, datetime)
        assert order.created_at.year == 2024
        assert order.created_at.tzinfo is not None

    def test_multiple_rows_all_inserted(self, store: OrdersStore, tmp_path: Path) -> None:
        csv_path = tmp_path / "multi.csv"
        csv_path.write_text(
            "order_id,amount_cents,stripe_charge_id,created_at\n"
            f"ord_001,1000,ch_aaa,{_CREATED_AT}\n"
            f"ord_002,2000,ch_bbb,{_CREATED_AT}\n"
            f"ord_003,3000,ch_ccc,{_CREATED_AT}\n",
            encoding="utf-8",
        )
        count = store.load_from_csv(csv_path)
        assert count == 3

    def test_duplicate_stripe_charge_id_raises_integrity_error(
        self, store: OrdersStore, sample_csv: Path, tmp_path: Path
    ) -> None:
        store.load_from_csv(sample_csv)
        dup_csv = tmp_path / "dup.csv"
        dup_csv.write_text(
            "order_id,amount_cents,stripe_charge_id,created_at\n"
            f"ord_999,5000,{_CHARGE_ID},{_CREATED_AT}\n",
            encoding="utf-8",
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.load_from_csv(dup_csv)

    def test_empty_csv_inserts_zero_rows(self, store: OrdersStore, tmp_path: Path) -> None:
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text(
            "order_id,amount_cents,stripe_charge_id,created_at\n",
            encoding="utf-8",
        )
        count = store.load_from_csv(empty_csv)
        assert count == 0
        assert store.get_all_orders() == []


class TestGetOrderByChargeId:
    def test_returns_none_when_charge_id_absent(self, store: OrdersStore) -> None:
        assert store.get_order_by_charge_id("ch_does_not_exist") is None

    def test_returns_none_on_empty_store(self, store: OrdersStore) -> None:
        assert store.get_order_by_charge_id(_CHARGE_ID) is None

    def test_correct_amount_cents_returned_after_insert(
        self, store: OrdersStore, sample_csv: Path
    ) -> None:
        store.load_from_csv(sample_csv)
        order = store.get_order_by_charge_id(_CHARGE_ID)
        assert order is not None
        assert order.amount_cents == _AMOUNT_CENTS

    def test_created_at_is_timezone_aware_datetime(
        self, store: OrdersStore, sample_csv: Path
    ) -> None:
        store.load_from_csv(sample_csv)
        order = store.get_order_by_charge_id(_CHARGE_ID)
        assert order is not None
        assert isinstance(order.created_at, datetime)
        assert order.created_at == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


class TestGetAllOrders:
    def test_empty_store_returns_empty_list(self, store: OrdersStore) -> None:
        assert store.get_all_orders() == []

    def test_returns_all_inserted_orders(self, store: OrdersStore, tmp_path: Path) -> None:
        csv_path = tmp_path / "orders.csv"
        csv_path.write_text(
            "order_id,amount_cents,stripe_charge_id,created_at\n"
            f"ord_001,1000,ch_aaa,{_CREATED_AT}\n"
            f"ord_002,2000,ch_bbb,{_CREATED_AT}\n",
            encoding="utf-8",
        )
        store.load_from_csv(csv_path)
        orders = store.get_all_orders()
        assert len(orders) == 2
        assert {o.stripe_charge_id for o in orders} == {"ch_aaa", "ch_bbb"}
        assert {o.amount_cents for o in orders} == {1000, 2000}


class TestLoadFromSqlite:
    def test_round_trip_from_external_db(
        self, store: OrdersStore, tmp_path: Path, sample_csv: Path
    ) -> None:
        src = OrdersStore(tmp_path / "src.db")
        src.load_from_csv(sample_csv)
        src.close()

        count = store.load_from_sqlite(tmp_path / "src.db")
        assert count == 1
        order = store.get_order_by_charge_id(_CHARGE_ID)
        assert order is not None
        assert order.amount_cents == _AMOUNT_CENTS
        assert order.order_id == _ORDER_ID

    def test_duplicate_from_external_db_raises_integrity_error(
        self, store: OrdersStore, tmp_path: Path, sample_csv: Path
    ) -> None:
        store.load_from_csv(sample_csv)
        src = OrdersStore(tmp_path / "src.db")
        src.load_from_csv(sample_csv)
        src.close()

        with pytest.raises(sqlite3.IntegrityError):
            store.load_from_sqlite(tmp_path / "src.db")

    def test_multiple_rows_from_external_db(
        self, store: OrdersStore, tmp_path: Path
    ) -> None:
        csv_path = tmp_path / "multi.csv"
        csv_path.write_text(
            "order_id,amount_cents,stripe_charge_id,created_at\n"
            f"ord_001,1000,ch_aaa,{_CREATED_AT}\n"
            f"ord_002,2000,ch_bbb,{_CREATED_AT}\n",
            encoding="utf-8",
        )
        src = OrdersStore(tmp_path / "src.db")
        src.load_from_csv(csv_path)
        src.close()

        count = store.load_from_sqlite(tmp_path / "src.db")
        assert count == 2
        assert len(store.get_all_orders()) == 2
