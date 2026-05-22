"""stripe-billing-reconciler: reconcile Stripe charges against internal orders."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("stripe-billing-reconciler")
except PackageNotFoundError:
    __version__ = "unknown"

__all__: list[str] = ["__version__"]
