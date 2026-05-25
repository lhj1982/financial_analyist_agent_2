"""OpenAI function-calling tool definitions + dispatcher."""
from __future__ import annotations

import json
from typing import Any, Callable

from . import data_sources, regime as regime_mod


# --- JSON Schemas for the LLM tool definitions ---
TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_volatility_snapshot",
            "description": (
                "Get VIX level and trend, plus MOVE (bond volatility) index. "
                "Used to assess market fear and volatility regime."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fear_greed_index",
            "description": "Get the current CNN Fear & Greed Index (0-100) and historical values.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_credit_market_health",
            "description": (
                "Get high-yield credit health (HYG, JNK, LQD). "
                "Critical for distinguishing Scenario 3 (opportunity) "
                "from Scenario 4 (systemic risk)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_macro_snapshot",
            "description": "Get USD (DXY), 10Y Treasury yield, gold, TLT — flight-to-safety signals.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_breadth",
            "description": (
                "Get SPY vs RSP vs IWM performance to assess market breadth "
                "(broad rally vs narrow mega-cap leadership)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_index_pullback",
            "description": "Get % drawdowns of SPY/QQQ/IWM/RSP from their 52-week highs.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bank_stress",
            "description": "Get bank ETF (KBE, KRE) performance — early warning for systemic stress.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_full_market_snapshot",
            "description": (
                "One-shot fetch of ALL key indicators (volatility, F&G, credit, "
                "macro, breadth, pullback, banks). Prefer this for the first call."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_market_regime",
            "description": (
                "Deterministically classify the current market into Scenario 1-5 "
                "based on a pre-fetched market snapshot. Always call "
                "get_full_market_snapshot first, then pass the result here."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "snapshot": {
                        "type": "object",
                        "description": (
                            "The dict returned by get_full_market_snapshot. "
                            "Pass it verbatim."
                        ),
                    }
                },
                "required": ["snapshot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_quote",
            "description": "Get latest price, 52w high/low, and drawdown for a single ticker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Yahoo Finance ticker symbol (e.g. AAPL, SPY, NVDA, SAAB-B.ST).",
                    }
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "regime_to_ticker_suggestions",
            "description": (
                "Given a classified regime, return suggested ticker buckets "
                "(preferred and avoid) appropriate for that regime."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "regime": {
                        "type": "object",
                        "description": "Output from classify_market_regime.",
                    }
                },
                "required": ["regime"],
            },
        },
    },
]


# --- Dispatcher: name -> python callable ---
def _classify_market_regime(snapshot: dict) -> dict:
    return regime_mod.classify_regime(snapshot)


def _regime_to_ticker_suggestions(regime: dict) -> dict:
    return regime_mod.regime_to_ticker_suggestions(regime)


DISPATCH: dict[str, Callable[..., Any]] = {
    "get_volatility_snapshot": data_sources.get_volatility_snapshot,
    "get_fear_greed_index": data_sources.get_fear_greed_index,
    "get_credit_market_health": data_sources.get_credit_market_health,
    "get_macro_snapshot": data_sources.get_macro_snapshot,
    "get_market_breadth": data_sources.get_market_breadth,
    "get_index_pullback": data_sources.get_index_pullback,
    "get_bank_stress": data_sources.get_bank_stress,
    "get_full_market_snapshot": data_sources.get_full_market_snapshot,
    "classify_market_regime": _classify_market_regime,
    "get_ticker_quote": data_sources.get_ticker_quote,
    "regime_to_ticker_suggestions": _regime_to_ticker_suggestions,
}


def dispatch_tool(name: str, arguments_json: str | dict) -> str:
    """Run a tool by name and return its result as a JSON string."""
    if name not in DISPATCH:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        args = (
            arguments_json if isinstance(arguments_json, dict)
            else json.loads(arguments_json or "{}")
        )
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Bad arguments JSON: {e}"})

    try:
        result = DISPATCH[name](**args) if args else DISPATCH[name]()
    except TypeError as e:
        return json.dumps({"error": f"Bad args for {name}: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Tool {name} failed: {e}"})

    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError) as e:
        return json.dumps({"error": f"Result not serializable: {e}"})
