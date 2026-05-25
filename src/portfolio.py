"""Portfolio analyzer.

Reads the simple portfolio JSON format:

    {
      "positions": [
        {"ticker": "AAPL", "buy_price": 150.0, "shares": 50, "category": "stock"},
        {"ticker": "AVANZA-GLOBAL", "value_sek": 134585, "category": "fund"},
        ...
      ],
      "cash": 20000
    }

Funds (which can't be price-fetched via yfinance) are treated as opaque
value blocks — we trust the `value_sek` field and use the ticker label for
LLM context (e.g. "this is a global equity fund").
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .data_sources import get_ticker_quote


def load_portfolio(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Portfolio file not found: {p}")
    with open(p) as f:
        return json.load(f)


def _is_priceable(pos: dict) -> bool:
    """Returns True if this position has a tradable ticker we can fetch."""
    return (
        pos.get("category") in ("stock", "etf")
        and "shares" in pos
        and "buy_price" in pos
    )


def analyze_portfolio(portfolio: dict) -> dict:
    """Compute per-position P&L, sizing, and portfolio-level stats.

    All values reported in the position's native currency for P&L, plus a
    combined view assuming reported `value_sek` for funds (Avanza-style).
    For mixed-currency portfolios we don't attempt full FX normalization in
    MVP — we expose raw numbers and let the LLM reason about it.
    """
    positions_in = portfolio.get("positions", [])
    cash = portfolio.get("cash", 0)

    analyzed: list[dict] = []
    total_value_native_buckets: dict[str, float] = {}  # currency -> sum

    for pos in positions_in:
        ticker = pos.get("ticker")
        category = pos.get("category", "stock")

        if _is_priceable(pos):
            shares = pos["shares"]
            buy_price = pos["buy_price"]
            cost_basis = shares * buy_price

            quote = get_ticker_quote(ticker)
            if "error" in quote:
                analyzed.append({
                    "ticker": ticker,
                    "category": category,
                    "error": quote["error"],
                    "shares": shares,
                    "buy_price": buy_price,
                    "cost_basis": cost_basis,
                })
                continue

            last = quote["last_price"]
            currency = quote.get("currency", "USD")
            market_value = round(shares * last, 2)
            pnl = round(market_value - cost_basis, 2)
            pnl_pct = round((last / buy_price - 1) * 100, 2) if buy_price else None

            total_value_native_buckets[currency] = (
                total_value_native_buckets.get(currency, 0) + market_value
            )

            analyzed.append({
                "ticker": ticker,
                "category": category,
                "currency": currency,
                "shares": shares,
                "buy_price": buy_price,
                "last_price": last,
                "cost_basis": round(cost_basis, 2),
                "market_value": market_value,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
                "drawdown_from_52w_high_pct": quote.get("drawdown_from_52w_high_pct"),
            })
        else:
            # Fund — opaque value
            value_sek = pos.get("value_sek")
            total_value_native_buckets["SEK"] = (
                total_value_native_buckets.get("SEK", 0) + (value_sek or 0)
            )
            analyzed.append({
                "ticker": ticker,
                "category": category,
                "currency": "SEK",
                "shares": None,
                "value_sek": value_sek,
                "note": "Fund — opaque, no per-share pricing.",
            })

    # Position sizing (% of portfolio) — naive, mixes currencies.
    # For an Avanza-style portfolio mostly in SEK + USD this is acceptable for MVP.
    total_value = sum(total_value_native_buckets.values()) + cash
    for p in analyzed:
        v = p.get("market_value") or p.get("value_sek") or 0
        p["portfolio_weight_pct"] = round((v / total_value) * 100, 2) if total_value else 0

    # Concentration checks
    largest = max(analyzed, key=lambda x: x.get("portfolio_weight_pct", 0), default=None)
    losers = sorted(
        [p for p in analyzed if (p.get("unrealized_pnl_pct") or 0) < -20],
        key=lambda x: x.get("unrealized_pnl_pct", 0),
    )
    winners = sorted(
        [p for p in analyzed if (p.get("unrealized_pnl_pct") or 0) > 20],
        key=lambda x: x.get("unrealized_pnl_pct", 0),
        reverse=True,
    )

    return {
        "positions": analyzed,
        "cash": cash,
        "total_value_estimate": round(total_value, 2),
        "value_by_currency": {k: round(v, 2) for k, v in total_value_native_buckets.items()},
        "cash_pct": round((cash / total_value) * 100, 2) if total_value else 0,
        "num_positions": len(analyzed),
        "largest_position": (
            {"ticker": largest.get("ticker"), "weight_pct": largest.get("portfolio_weight_pct")}
            if largest else None
        ),
        "deep_losers": [
            {"ticker": p["ticker"], "pnl_pct": p.get("unrealized_pnl_pct")}
            for p in losers
        ],
        "big_winners": [
            {"ticker": p["ticker"], "pnl_pct": p.get("unrealized_pnl_pct")}
            for p in winners
        ],
        "flags": _flag_risks(analyzed, cash, total_value),
    }


def _flag_risks(positions: list[dict], cash: float, total_value: float) -> list[str]:
    flags = []
    if total_value > 0 and cash / total_value < 0.05:
        flags.append("Cash reserve < 5% — limited dry powder for Scenario 2/3 buys.")
    for p in positions:
        w = p.get("portfolio_weight_pct") or 0
        if w > 25:
            flags.append(f"{p['ticker']} concentration {w:.1f}% > 25%.")
    # Same-theme detection (very basic)
    tech_tickers = {"MSFT", "NVDA", "META", "AAPL", "GOOGL", "TSLA", "SEMI.DE",
                    "AMZN", "SWEDBANK-ROBUR-TECHNOLOGY-A", "JPM-US-SELECT-EQUITY-A-USD"}
    tech_weight = sum(
        (p.get("portfolio_weight_pct") or 0)
        for p in positions if p["ticker"] in tech_tickers
    )
    if tech_weight > 40:
        flags.append(
            f"Estimated tech-adjacent exposure ~{tech_weight:.1f}% > 40%."
        )
    defense_tickers = {"SAAB-B.ST", "MILDEF.ST"}
    def_weight = sum(
        (p.get("portfolio_weight_pct") or 0)
        for p in positions if p["ticker"] in defense_tickers
    )
    if def_weight > 15:
        flags.append(
            f"Defense theme concentration ~{def_weight:.1f}% — single-theme risk."
        )
    return flags
