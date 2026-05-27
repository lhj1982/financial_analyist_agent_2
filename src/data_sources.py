"""Market data fetchers.

All functions return plain Python dicts / floats so they can be JSON-serialized
and passed to the LLM as tool results.

The cache layer is intentionally simple: in-process TTL cache. For a CLI tool
that runs ad-hoc this is fine. Switch to Redis/file cache if needed later.
"""
from __future__ import annotations

import time
from typing import Any

import requests
import yfinance as yf

from .config import DATA_CACHE_TTL, TICKERS

# ----- tiny in-process TTL cache -----
_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, fetcher, ttl: int = DATA_CACHE_TTL):
    now = time.time()
    if key in _cache:
        ts, value = _cache[key]
        if now - ts < ttl:
            return value
    value = fetcher()
    _cache[key] = (now, value)
    return value


# ----- yfinance helpers -----
def _get_history(ticker: str, period: str = "3mo") -> list[dict]:
    """Return a list of {date, close} for a ticker, oldest first."""
    def fetch():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, auto_adjust=True)
            if hist.empty:
                return []
            return [
                {"date": str(idx.date()), "close": float(row["Close"])}
                for idx, row in hist.iterrows()
            ]
        except Exception as e:
            return [{"error": f"yfinance fetch failed for {ticker}: {e}"}]
    return _cached(f"hist:{ticker}:{period}", fetch)


def _latest_close(ticker: str) -> float | None:
    hist = _get_history(ticker, period="5d")
    if not hist or "error" in hist[0]:
        return None
    return hist[-1]["close"]


def _pct_change(ticker: str, n_days: int) -> float | None:
    """Return % change of `ticker` over the last `n_days` trading days."""
    hist = _get_history(ticker, period="6mo")
    if not hist or "error" in hist[0]:
        return None
    if len(hist) < n_days + 1:
        return None
    start = hist[-(n_days + 1)]["close"]
    end = hist[-1]["close"]
    if start == 0:
        return None
    return round((end / start - 1) * 100, 2)


def _drawdown_from_52w_high(ticker: str) -> float | None:
    """Return current % drawdown from 52-week high (negative number)."""
    hist = _get_history(ticker, period="1y")
    if not hist or "error" in hist[0]:
        return None
    closes = [h["close"] for h in hist]
    high = max(closes)
    last = closes[-1]
    if high == 0:
        return None
    return round((last / high - 1) * 100, 2)


# ----- public fetchers used as agent tools -----
def get_volatility_snapshot() -> dict:
    """VIX, MOVE, plus short-term VIX trend."""
    vix_hist = _get_history(TICKERS["vix"], period="3mo")
    move = _latest_close(TICKERS["move"])
    if not vix_hist or "error" in vix_hist[0]:
        return {"error": "Failed to fetch VIX"}
    vix_last = vix_hist[-1]["close"]
    vix_5d_ago = vix_hist[-6]["close"] if len(vix_hist) >= 6 else None
    vix_20d_ago = vix_hist[-21]["close"] if len(vix_hist) >= 21 else None
    return {
        "vix": round(vix_last, 2),
        "vix_5d_change_pct": round((vix_last / vix_5d_ago - 1) * 100, 2) if vix_5d_ago else None,
        "vix_20d_change_pct": round((vix_last / vix_20d_ago - 1) * 100, 2) if vix_20d_ago else None,
        "vix_20d_avg": round(sum(h["close"] for h in vix_hist[-20:]) / min(20, len(vix_hist)), 2),
        "move_index": round(move, 2) if move else None,
    }


def get_fear_greed_index() -> dict:
    """CNN Fear & Greed Index via their unofficial JSON endpoint."""
    def fetch():
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            fg = data.get("fear_and_greed", {})
            return {
                "value": round(fg.get("score", 0), 1),
                "rating": fg.get("rating"),
                "previous_close": round(fg.get("previous_close", 0), 1),
                "previous_1_week": round(fg.get("previous_1_week", 0), 1),
                "previous_1_month": round(fg.get("previous_1_month", 0), 1),
                "previous_1_year": round(fg.get("previous_1_year", 0), 1),
            }
        except Exception as e:
            return {"error": f"Fear & Greed fetch failed: {e}"}
    return _cached("fear_greed", fetch)


def get_credit_market_health() -> dict:
    """HYG / JNK / LQD prices and short-term changes — the S3 vs S4 discriminator."""
    return {
        "hyg_price": _latest_close(TICKERS["hyg"]),
        "hyg_5d_change_pct": _pct_change(TICKERS["hyg"], 5),
        "hyg_20d_change_pct": _pct_change(TICKERS["hyg"], 20),
        "jnk_price": _latest_close(TICKERS["jnk"]),
        "jnk_5d_change_pct": _pct_change(TICKERS["jnk"], 5),
        "lqd_price": _latest_close(TICKERS["lqd"]),
        "lqd_5d_change_pct": _pct_change(TICKERS["lqd"], 5),
        # spread proxy: LQD - HYG relative move (when HYG falls relative to LQD, spreads widen)
        "credit_stress_proxy": (
            round((_pct_change(TICKERS["hyg"], 5) or 0) - (_pct_change(TICKERS["lqd"], 5) or 0), 2)
        ),
    }


def get_macro_snapshot() -> dict:
    """USD index, 10Y yield, gold — flight-to-safety signals."""
    dxy_hist = _get_history(TICKERS["dxy"], period="3mo")
    dxy_last = dxy_hist[-1]["close"] if dxy_hist and "error" not in dxy_hist[0] else None
    dxy_20d_ago = dxy_hist[-21]["close"] if dxy_hist and len(dxy_hist) >= 21 else None

    tnx_last = _latest_close(TICKERS["tnx"])
    # ^TNX is yield * 10 (e.g. 4.20% shows as 42.0)
    yield_10y = round(tnx_last / 10, 2) if tnx_last else None

    return {
        "dxy": round(dxy_last, 2) if dxy_last else None,
        "dxy_20d_change_pct": (
            round((dxy_last / dxy_20d_ago - 1) * 100, 2) if dxy_last and dxy_20d_ago else None
        ),
        "yield_10y_pct": yield_10y,
        "gold_price": _latest_close(TICKERS["gld"]),
        "gold_20d_change_pct": _pct_change(TICKERS["gld"], 20),
        "tlt_price": _latest_close(TICKERS["tlt"]),
        "tlt_20d_change_pct": _pct_change(TICKERS["tlt"], 20),
    }


def get_market_breadth() -> dict:
    """SPY vs RSP vs IWM — leadership / breadth signals."""
    spy = _latest_close(TICKERS["spy"])
    rsp = _latest_close(TICKERS["rsp"])
    iwm = _latest_close(TICKERS["iwm"])

    spy_20d = _pct_change(TICKERS["spy"], 20)
    rsp_20d = _pct_change(TICKERS["rsp"], 20)
    iwm_20d = _pct_change(TICKERS["iwm"], 20)

    # RSP/SPY ratio change tells us breadth direction
    spy_hist = _get_history(TICKERS["spy"], period="3mo")
    rsp_hist = _get_history(TICKERS["rsp"], period="3mo")
    breadth_ratio_trend = None
    if spy_hist and rsp_hist and "error" not in spy_hist[0] and "error" not in rsp_hist[0]:
        n = min(20, len(spy_hist), len(rsp_hist))
        ratio_now = rsp_hist[-1]["close"] / spy_hist[-1]["close"]
        ratio_then = rsp_hist[-n]["close"] / spy_hist[-n]["close"]
        breadth_ratio_trend = round((ratio_now / ratio_then - 1) * 100, 2)

    return {
        "spy_price": spy,
        "rsp_price": rsp,
        "iwm_price": iwm,
        "spy_20d_change_pct": spy_20d,
        "rsp_20d_change_pct": rsp_20d,
        "iwm_20d_change_pct": iwm_20d,
        "rsp_minus_spy_20d_pct": (
            round(rsp_20d - spy_20d, 2) if rsp_20d is not None and spy_20d is not None else None
        ),
        "iwm_minus_spy_20d_pct": (
            round(iwm_20d - spy_20d, 2) if iwm_20d is not None and spy_20d is not None else None
        ),
        "breadth_ratio_trend_pct": breadth_ratio_trend,
        "interpretation": (
            "broadening" if breadth_ratio_trend and breadth_ratio_trend > 0
            else "narrowing" if breadth_ratio_trend and breadth_ratio_trend < 0
            else "flat"
        ),
    }


def get_index_pullback() -> dict:
    """% drawdown of major indices from 52-week high."""
    return {
        "spy_drawdown_pct": _drawdown_from_52w_high(TICKERS["spy"]),
        "qqq_drawdown_pct": _drawdown_from_52w_high(TICKERS["qqq"]),
        "iwm_drawdown_pct": _drawdown_from_52w_high(TICKERS["iwm"]),
        "rsp_drawdown_pct": _drawdown_from_52w_high(TICKERS["rsp"]),
    }


def get_bank_stress() -> dict:
    """Bank ETFs — early warning for systemic stress."""
    return {
        "kbe_price": _latest_close(TICKERS["kbe"]),
        "kbe_5d_change_pct": _pct_change(TICKERS["kbe"], 5),
        "kbe_20d_change_pct": _pct_change(TICKERS["kbe"], 20),
        "kre_price": _latest_close(TICKERS["kre"]),
        "kre_5d_change_pct": _pct_change(TICKERS["kre"], 5),
        "kre_20d_change_pct": _pct_change(TICKERS["kre"], 20),
    }


def get_ticker_quote(ticker: str) -> dict:
    """Latest price + key stats for a single ticker (used in portfolio analysis)."""
    def fetch():
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info if hasattr(t, "fast_info") else {}
            hist = t.history(period="1y", auto_adjust=True)
            if hist.empty:
                return {"ticker": ticker, "error": "no data"}
            last = float(hist["Close"].iloc[-1])
            high_52w = float(hist["Close"].max())
            low_52w = float(hist["Close"].min())
            return {
                "ticker": ticker,
                "last_price": round(last, 2),
                "high_52w": round(high_52w, 2),
                "low_52w": round(low_52w, 2),
                "drawdown_from_52w_high_pct": round((last / high_52w - 1) * 100, 2),
                "currency": getattr(info, "currency", None) or "USD",
            }
        except Exception as e:
            return {"ticker": ticker, "error": str(e)}
    return _cached(f"quote:{ticker}", fetch)


def _fmt_market_cap(raw_usd: float) -> str:
    """Format a raw dollar market cap into a human-readable string (e.g. '$1.01T')."""
    if raw_usd >= 1e12:
        return f"${raw_usd / 1e12:.2f}T"
    if raw_usd >= 1e9:
        return f"${raw_usd / 1e9:.1f}B"
    return f"${raw_usd / 1e6:.1f}M"


def get_stock_analysis(ticker: str) -> dict:
    """Fundamentals, technicals, and analyst consensus for a single ticker."""
    def fetch():
        try:
            t = yf.Ticker(ticker)
            info = t.info
            hist = t.history(period="1y", auto_adjust=True)
            if hist.empty:
                return {"ticker": ticker, "error": "no price history"}

            closes = hist["Close"]

            # Prefer fast_info.last_price (real-time) over history close
            try:
                last = float(t.fast_info.last_price)
            except Exception:
                last = float(closes.iloc[-1])

            high_52w = float(closes.max())
            low_52w = float(closes.min())

            ma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
            ma200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None

            delta = closes.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else None
            rsi = round(100 - 100 / (1 + rs), 2) if rs is not None else None

            avg_vol_20d = (
                float(hist["Volume"].rolling(20).mean().iloc[-1])
                if len(hist) >= 20 else None
            )

            # Market cap: fast_info is more reliable than info["marketCap"]
            try:
                market_cap_raw = float(t.fast_info.market_cap)
            except Exception:
                market_cap_raw = float(info.get("marketCap") or 0) or None

            # Compute P/E directly from EPS — avoids stale/mismatched info["trailingPE"]
            trailing_eps = info.get("trailingEps")
            forward_eps = info.get("forwardEps")
            pe_trailing = round(last / trailing_eps, 2) if trailing_eps and trailing_eps > 0 else None
            pe_forward = round(last / forward_eps, 2) if forward_eps and forward_eps > 0 else None

            target = info.get("targetMeanPrice")
            return {
                "ticker": ticker.upper(),
                "name": info.get("shortName") or info.get("longName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": _fmt_market_cap(market_cap_raw) if market_cap_raw else None,
                "market_cap_usd": round(market_cap_raw, 0) if market_cap_raw else None,
                "beta": info.get("beta"),
                # Valuation — P/E computed from EPS so it's always price-consistent
                "pe_trailing": pe_trailing,
                "pe_forward": pe_forward,
                "trailing_eps": round(trailing_eps, 2) if trailing_eps else None,
                "forward_eps": round(forward_eps, 2) if forward_eps else None,
                "ps_ratio": round(info.get("priceToSalesTrailing12Months", 0), 2) if info.get("priceToSalesTrailing12Months") else None,
                "pb_ratio": round(info.get("priceToBook", 0), 2) if info.get("priceToBook") else None,
                # Growth & quality
                "revenue_growth_yoy": info.get("revenueGrowth"),
                "earnings_growth_yoy": info.get("earningsGrowth"),
                "gross_margin": info.get("grossMargins"),
                "operating_margin": info.get("operatingMargins"),
                "net_margin": info.get("profitMargins"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "free_cash_flow_bn": round(info.get("freeCashflow", 0) / 1e9, 2) if info.get("freeCashflow") else None,
                # Price & technicals
                "current_price": round(last, 2),
                "high_52w": round(high_52w, 2),
                "low_52w": round(low_52w, 2),
                "drawdown_from_52w_high_pct": round((last / high_52w - 1) * 100, 2),
                "ma50": round(ma50, 2) if ma50 else None,
                "ma200": round(ma200, 2) if ma200 else None,
                "price_vs_ma50_pct": round((last / ma50 - 1) * 100, 2) if ma50 else None,
                "price_vs_ma200_pct": round((last / ma200 - 1) * 100, 2) if ma200 else None,
                "rsi_14": rsi,
                "momentum_5d_pct": _pct_change(ticker, 5),
                "momentum_20d_pct": _pct_change(ticker, 20),
                "momentum_60d_pct": _pct_change(ticker, 60),
                "avg_volume_20d": int(avg_vol_20d) if avg_vol_20d else None,
                # Analyst consensus
                "analyst_recommendation": info.get("recommendationKey"),
                "analyst_mean_rating": info.get("recommendationMean"),  # 1=Strong Buy … 5=Sell
                "analyst_target_price": round(target, 2) if target else None,
                "analyst_target_upside_pct": round((target / last - 1) * 100, 2) if target else None,
                "analyst_count": info.get("numberOfAnalystOpinions"),
            }
        except Exception as e:
            return {"ticker": ticker, "error": str(e)}
    return _cached(f"analysis:{ticker.upper()}", fetch)


def get_full_market_snapshot() -> dict:
    """One-shot — all key inputs the regime classifier needs."""
    return {
        "volatility": get_volatility_snapshot(),
        "fear_greed": get_fear_greed_index(),
        "credit": get_credit_market_health(),
        "macro": get_macro_snapshot(),
        "breadth": get_market_breadth(),
        "pullback": get_index_pullback(),
        "banks": get_bank_stress(),
    }
