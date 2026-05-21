#!/usr/bin/env bash
# run_local_demo.sh — run the reconciler against local mock data.
# No live Stripe key is needed; STRIPE_MOCK_CHARGES_FILE redirects the
# charges fetcher to read examples/mock_charges.json instead of the API.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v stripe-reconcile &>/dev/null; then
    echo "stripe-reconcile not found. Activate your virtual environment and install the package:" >&2
    echo "  pip install -e ." >&2
    exit 1
fi

export STRIPE_API_KEY="sk_test_fake_key_local_demo_only"
export STRIPE_MOCK_CHARGES_FILE="${SCRIPT_DIR}/mock_charges.json"

echo "================================================================"
echo " Stripe Billing Reconciler — local demo"
echo " Orders  : ${SCRIPT_DIR}/sample_orders.csv  (20 rows)"
echo " Charges : ${SCRIPT_DIR}/mock_charges.json   (22 mock charges)"
echo "================================================================"
echo ""
echo "Expected: 5 discrepancies"
echo "  2 x AMOUNT_MISMATCH       (ord_2018: 4999c vs 5000c; ord_2019: 12900c vs 13000c)"
echo "  1 x ORDER_NOT_IN_STRIPE   (ord_2020 -> ch_ghost_999 absent from Stripe)"
echo "  2 x CHARGE_NOT_IN_ORDERS  (ch_demo_020, ch_demo_021 have no matching order)"
echo ""
echo "-- table -------------------------------------------------------"

set +e
stripe-reconcile reconcile \
    --csv "${SCRIPT_DIR}/sample_orders.csv" \
    --format table
demo_exit=$?
set -e

echo ""
echo "-- json --------------------------------------------------------"

set +e
stripe-reconcile reconcile \
    --csv "${SCRIPT_DIR}/sample_orders.csv" \
    --format json
set -e

echo ""
echo "Exit code: ${demo_exit}  (1 = discrepancies found, 0 = clean)"
exit "${demo_exit}"
