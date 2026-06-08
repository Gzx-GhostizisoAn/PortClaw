"""Backward-compatible import wrapper.

Use src.ledger.portfolio_loader.load_portfolio_snapshot for new code.
"""

from .ledger.portfolio_loader import load_portfolio_snapshot as load_sample_snapshot

__all__ = ["load_sample_snapshot"]
