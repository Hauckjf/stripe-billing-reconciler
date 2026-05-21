"""Integration test: full reconcile flow with fixture JSON and CSV files."""
from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from stripe_reconciler.client import StripeClient
from stripe_reconciler.fetchers.charges import fetch_all_charges
from stripe_reconciler.models import DiscrepancyKind
from stripe_reconciler.reconciler import reconcile
from stripe_reconciler.store import OrdersStore

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _make_list_object(payload: dict[str, Any]) -> MagicMock:
    """Build a mock stripe.ListObject from a fixture JSON payload."""
    page: MagicMock = MagicMock()
    page.has_more = payload["has_more"]
    page.data = [
        SimpleNamespace(
            id=ch["id"],
            amount=ch["amount"],
            currency=ch["currency"],
            created=ch["created"],
            status=ch["status"],
        )
        for ch in payload["data"]
    ]
    return page


@pytest.fixture()
def orders_store(tmp_path: Path) -> Generator[OrdersStore, None, None]:
    store = OrdersStore(tmp_path / "integration.db")
    store.load_from_csv(_FIXTURES / "orders.csv")
    yield store
    store.close()


@pytest.fixture()
def mock_client() -> MagicMock:
    """StripeClient whose list_charges returns page1 then page2 from fixtures."""
    page1 = _make_list_object(
        json.loads((_FIXTURES / "charges_page1.json").read_text(encoding="utf-8"))
    )
    page2 = _make_list_object(
        json.loads((_FIXTURES / "charges_page2.json").read_text(encoding="utf-8"))
    )
    client: MagicMock = MagicMock(spec=StripeClient)
    client.list_charges.side_effect = [page1, page2]
    return client


class TestReconcileWithFixtures:
    def test_exactly_two_discrepancies_found(
        self, mock_client: MagicMock, orders_store: OrdersStore
    ) -> None:
        charges = list(
            fetch_all_charges(
                mock_client, created_gte=None, created_lte=None, page_size=5
            )
        )
        result = reconcile(charges, orders_store)
        assert len(result) == 2

    def test_discrepancy_kinds_are_amount_mismatch_and_order_not_in_stripe(
        self, mock_client: MagicMock, orders_store: OrdersStore
    ) -> None:
        charges = list(
            fetch_all_charges(
                mock_client, created_gte=None, created_lte=None, page_size=5
            )
        )
        result = reconcile(charges, orders_store)
        kinds = {d.kind for d in result}
        assert kinds == {
            DiscrepancyKind.AMOUNT_MISMATCH,
            DiscrepancyKind.ORDER_NOT_IN_STRIPE,
        }

    def test_both_discrepancies_have_non_empty_detail(
        self, mock_client: MagicMock, orders_store: OrdersStore
    ) -> None:
        charges = list(
            fetch_all_charges(
                mock_client, created_gte=None, created_lte=None, page_size=5
            )
        )
        result = reconcile(charges, orders_store)
        assert all(d.detail for d in result)

    def test_amount_mismatch_stripe_differs_from_order(
        self, mock_client: MagicMock, orders_store: OrdersStore
    ) -> None:
        """Edge case: AMOUNT_MISMATCH fields carry both the Stripe and order amounts."""
        charges = list(
            fetch_all_charges(
                mock_client, created_gte=None, created_lte=None, page_size=5
            )
        )
        result = reconcile(charges, orders_store)
        mismatch = next(
            d for d in result if d.kind == DiscrepancyKind.AMOUNT_MISMATCH
        )
        assert mismatch.charge_id == "ch_005"
        assert mismatch.order_id == "ord_005"
        assert mismatch.stripe_amount_cents == 1500
        assert mismatch.order_amount_cents == 1000
        assert mismatch.stripe_amount_cents != mismatch.order_amount_cents

    def test_cursor_advances_between_pages(
        self, mock_client: MagicMock, orders_store: OrdersStore
    ) -> None:
        """Edge case: paginator passes the last charge id of page1 as starting_after."""
        list(
            fetch_all_charges(
                mock_client, created_gte=None, created_lte=None, page_size=5
            )
        )
        assert mock_client.list_charges.call_count == 2
        second_call_kwargs = mock_client.list_charges.call_args_list[1].kwargs
        # cursor must be the last id from page1 (ch_005)
        assert second_call_kwargs["starting_after"] == "ch_005"
