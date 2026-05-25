"""Configuration and constants."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
DATA_CACHE_TTL: int = int(os.getenv("DATA_CACHE_TTL", "300"))

DEFAULT_PORTFOLIO_PATH: Path = PROJECT_ROOT / "portfolio.json"

# --- Ticker symbol mapping for data fetching ---
# Yahoo Finance tickers for the key indicators
TICKERS = {
    "vix": "^VIX",
    "move": "^MOVE",          # bond market volatility (may be unavailable on yfinance)
    "spx": "^GSPC",
    "spy": "SPY",
    "qqq": "QQQ",
    "iwm": "IWM",
    "rsp": "RSP",
    "hyg": "HYG",             # high-yield credit
    "jnk": "JNK",             # high-yield credit (alt)
    "lqd": "LQD",             # investment-grade credit
    "tlt": "TLT",             # long Treasuries
    "shy": "SHY",             # short Treasuries
    "gld": "GLD",             # gold
    "dxy": "DX-Y.NYB",        # USD index
    "tnx": "^TNX",            # 10y yield (in tenths of %)
    "kbe": "KBE",             # banks ETF
    "kre": "KRE",             # regional banks ETF
}

# --- Regime thresholds (tunable) ---
THRESHOLDS = {
    # Scenario 1 — normal pullback
    "s1_vix_low": 18.0,
    "s1_vix_high": 25.0,
    "s1_fg_low": 25,
    "s1_fg_high": 45,
    "s1_pullback_min": -5.0,
    "s1_pullback_max": -3.0,

    # Scenario 2 — panic pullback
    "s2_vix_low": 25.0,
    "s2_vix_high": 35.0,
    "s2_fg_max": 25,
    "s2_pullback_max": -7.0,  # at least -7%

    # Scenario 3 — extreme panic
    "s3_vix_min": 35.0,
    "s3_fg_max": 15,

    # Scenario 4 — systemic risk flags
    "s4_hyg_5d_drop": -3.0,       # HYG down >3% in 5 days
    "s4_dxy_20d_surge": 3.0,      # DXY up >3% in 20 days
    "s4_bank_5d_drop": -8.0,      # bank ETF down >8% in 5 days
    "s4_move_high": 140.0,         # MOVE > 140 = bond market stress
    "s4_vix_floor": 25.0,          # systemic risk requires VIX > 25

    # Scenario 5 — excessive greed
    "s5_vix_max": 15.0,
    "s5_fg_min": 75,
}

# --- Ticker universe tagged by regime suitability ---
TICKER_UNIVERSE = {
    "core_etfs": ["SPY", "VOO", "RSP", "QQQ", "IWM", "VTI"],
    "defensive": ["XLP", "XLU", "XLV", "BRK-B", "JNJ", "PG", "KO"],
    "quality_growth": ["MSFT", "GOOGL", "META", "AAPL", "V", "MA", "COST"],
    "rate_sensitive_upside": ["IWM", "XLF", "KRE", "XHB"],
    "safe_haven": ["GLD", "IAU", "TLT", "SHY", "BIL"],
    "credit_health_indicators": ["HYG", "JNK", "LQD"],
    "high_beta_avoid_in_s4": ["ARKK", "SOXL", "TQQQ", "UPRO"],
    "income_in_s5": ["SCHD", "VYM", "JEPI"],
}
