"""Stock universe configuration manager.

Loads the configurable trading universe from config/stock_universe.json.
Provides default NIFTY 50 primary symbols and extended symbols for widening
when scenario counts are short.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from app.core.config import PROJECT_ROOT

logger = logging.getLogger("tradezen.universe")

DEFAULT_UNIVERSE_CONFIG_PATH = PROJECT_ROOT / "config" / "stock_universe.json"

# Static fallback NIFTY 50 constituents
FALLBACK_NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL",
    "SBIN", "INFY", "ITC", "LT", "HINDUNILVR",
    "AXISBANK", "KOTAKBANK", "BAJFINANCE", "MARUTI", "HCLTECH",
    "SUNPHARMA", "TATAMOTORS", "NTPC", "ULTRACEMCO", "ONGC",
    "TITAN", "POWERGRID", "ADANIENT", "BAJAJFINSV", "TATASTEEL",
    "ASIANPAINT", "COALINDIA", "M&M", "JSWSTEEL", "NESTLEIND",
    "TECHM", "GRASIM", "CIPLA", "ADANIPORTS", "SBILIFE",
    "HDFCLIFE", "WIPRO", "DRREDDY", "BPCL", "BRITANNIA",
    "EICHERMOT", "HINDALCO", "TATACONSUM", "APOLLOHOSP", "DIVISLAB",
    "BAJAJ-AUTO", "LTIM", "HEROMOTOCO", "INDUSINDBK", "TRENT"
]

FALLBACK_EXTENDED = [
    "BEL", "HAL", "VEDL", "IOC", "ZOMATO", "DLF", "JIOFIN", "VBL",
    "CHOLAFIN", "PIDILITIND", "HAVELLS", "AMBUJACEM", "BANKBARODA",
    "SIEMENS", "PFC", "RECLTD", "GAIL", "ABB", "TORNTPHARM", "SRF"
]


def load_universe_config(config_path: Path = DEFAULT_UNIVERSE_CONFIG_PATH) -> Tuple[List[str], List[str]]:
    """Loads primary and extended symbols from config JSON.

    Returns:
        (primary_symbols, extended_symbols)
    """
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                primary = [s.strip().upper() for s in data.get("primary", []) if s.strip()]
                extended = [s.strip().upper() for s in data.get("extended", []) if s.strip()]
                if primary:
                    return primary, extended
        except Exception as exc:
            logger.warning("Could not read universe config from %s: %s. Using default NIFTY 50.", config_path, exc)

    return FALLBACK_NIFTY_50, FALLBACK_EXTENDED


def get_primary_symbols() -> List[str]:
    """Returns primary universe symbols (NIFTY 50)."""
    primary, _ = load_universe_config()
    return primary


def get_extended_symbols() -> List[str]:
    """Returns extended universe symbols used when scenario counts are short."""
    _, extended = load_universe_config()
    return extended


def get_full_universe() -> List[str]:
    """Returns primary + extended symbols combined without duplicates."""
    primary, extended = load_universe_config()
    seen = set()
    result = []
    for s in primary + extended:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result
