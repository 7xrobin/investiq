"""
ETF return presets for the portfolio simulation card.

These are illustrative long-run average annual returns (nominal, in EUR terms
where applicable) for well-known broad-market indices. They are deliberately
conservative round numbers for projection purposes — not guarantees, and not a
live data feed. Shared single source of truth for the Goals simulation UI.
"""
from __future__ import annotations

ETF_PRESETS: list[dict] = [
    {"key": "msci_world", "label": "MSCI World", "annual_return_pct": 7.0},
    {"key": "sp500", "label": "S&P 500", "annual_return_pct": 9.0},
    {"key": "ftse_all_world", "label": "FTSE All-World", "annual_return_pct": 7.0},
    {"key": "msci_em", "label": "MSCI Emerging Markets", "annual_return_pct": 6.0},
    {"key": "msci_acwi", "label": "MSCI ACWI", "annual_return_pct": 7.0},
    {"key": "eurostoxx50", "label": "EURO STOXX 50", "annual_return_pct": 6.5},
]

# Sensible default selection for the picker.
DEFAULT_PRESET_KEY = "msci_world"
