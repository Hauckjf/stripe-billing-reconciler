"""Public CLI entry point for the stripe-billing-reconciler package.

Re-exports the Click command group from stripe_reconciler so that
setuptools can wire up the ``stripe-reconciler`` console script without
duplicating the command definition.
"""

from __future__ import annotations

from stripe_reconciler.cli import main as main

__all__: list[str] = ["main"]
