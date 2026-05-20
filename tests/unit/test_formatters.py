"""Tests for output formatters (JSON, CSV, rich table)."""

from __future__ import annotations

import csv
import io
import json

from stripe_reconciler.formatters import to_csv, to_json, to_table
from stripe_reconciler.models import Discrepancy, DiscrepancyKind


def _discrepancy(
    kind: DiscrepancyKind = DiscrepancyKind.AMOUNT_MISMATCH,
    charge_id: str | None = "ch_001",
    order_id: str | None = "ord_001",
    stripe_amount_cents: int | None = 1500,
    order_amount_cents: int | None = 1450,
    detail: str = "delta = 1500 - 1450 = 50",
) -> Discrepancy:
    return Discrepancy(
        kind=kind,
        charge_id=charge_id,
        order_id=order_id,
        stripe_amount_cents=stripe_amount_cents,
        order_amount_cents=order_amount_cents,
        detail=detail,
    )


class TestToJson:
    def test_empty_list_returns_json_array(self) -> None:
        result = to_json([])
        assert result == "[]"
        assert json.loads(result) == []

    def test_single_discrepancy_serialised_correctly(self) -> None:
        parsed = json.loads(to_json([_discrepancy()]))
        assert len(parsed) == 1
        assert parsed[0]["kind"] == "AMOUNT_MISMATCH"
        assert parsed[0]["charge_id"] == "ch_001"
        assert parsed[0]["stripe_amount_cents"] == 1500
        assert parsed[0]["order_amount_cents"] == 1450

    def test_null_fields_serialised_as_json_null(self) -> None:
        d = _discrepancy(
            kind=DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
            order_id=None,
            order_amount_cents=None,
        )
        parsed = json.loads(to_json([d]))
        assert parsed[0]["order_id"] is None
        assert parsed[0]["order_amount_cents"] is None

    def test_output_is_pretty_printed(self) -> None:
        result = to_json([_discrepancy()])
        assert "\n" in result
        assert "  " in result

    def test_multiple_discrepancies(self) -> None:
        d1 = _discrepancy()
        d2 = _discrepancy(kind=DiscrepancyKind.DUPLICATE_CHARGE_ID, charge_id="ch_dup")
        parsed = json.loads(to_json([d1, d2]))
        assert len(parsed) == 2
        assert parsed[1]["kind"] == "DUPLICATE_CHARGE_ID"


class TestToCsv:
    def test_empty_list_returns_header_only(self) -> None:
        lines = to_csv([]).splitlines()
        assert len(lines) == 1
        assert lines[0] == "kind,charge_id,order_id,stripe_amount_cents,order_amount_cents,detail"

    def test_two_discrepancies_return_three_lines(self) -> None:
        d1 = _discrepancy()
        d2 = _discrepancy(
            kind=DiscrepancyKind.ORDER_NOT_IN_STRIPE,
            charge_id=None,
            order_id="ord_002",
            stripe_amount_cents=None,
        )
        assert len(to_csv([d1, d2]).splitlines()) == 3

    def test_none_fields_are_empty_strings_in_csv(self) -> None:
        d = _discrepancy(
            kind=DiscrepancyKind.ORDER_NOT_IN_STRIPE,
            charge_id=None,
            stripe_amount_cents=None,
        )
        lines = to_csv([d]).splitlines()
        row = next(csv.reader(io.StringIO(lines[1])))
        assert row[1] == ""  # charge_id
        assert row[3] == ""  # stripe_amount_cents

    def test_kind_serialised_as_string_value(self) -> None:
        d = _discrepancy(kind=DiscrepancyKind.DUPLICATE_CHARGE_ID)
        assert "DUPLICATE_CHARGE_ID" in to_csv([d])

    def test_amounts_serialised_as_integer_strings(self) -> None:
        d = _discrepancy(stripe_amount_cents=9999, order_amount_cents=9900)
        data_line = to_csv([d]).splitlines()[1]
        row = next(csv.reader(io.StringIO(data_line)))
        assert row[3] == "9999"
        assert row[4] == "9900"

    def test_detail_with_comma_is_quoted(self) -> None:
        d = _discrepancy(detail="order ord_1, charge ch_1")
        data_line = to_csv([d]).splitlines()[1]
        row = next(csv.reader(io.StringIO(data_line)))
        assert row[5] == "order ord_1, charge ch_1"


class TestToTable:
    def test_column_headers_present(self) -> None:
        result = to_table([])
        assert "Kind" in result
        assert "Charge ID" in result
        assert "Order ID" in result

    def test_discrepancy_values_in_output(self) -> None:
        d = _discrepancy()
        result = to_table([d])
        assert "ch_001" in result
        assert "ord_001" in result
        assert "AMOUNT_MISMATCH" in result

    def test_none_fields_not_rendered_as_none_literal(self) -> None:
        d = _discrepancy(
            kind=DiscrepancyKind.CHARGE_NOT_IN_ORDERS,
            order_id=None,
            order_amount_cents=None,
        )
        assert "None" not in to_table([d])

    def test_returns_nonempty_string(self) -> None:
        result = to_table([])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_multiple_rows_all_appear(self) -> None:
        d1 = _discrepancy(charge_id="ch_aaa")
        d2 = _discrepancy(charge_id="ch_bbb", kind=DiscrepancyKind.CHARGE_NOT_IN_ORDERS)
        result = to_table([d1, d2])
        assert "ch_aaa" in result
        assert "ch_bbb" in result
