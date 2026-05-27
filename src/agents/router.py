"""Lightweight intent router.

Classifies the user's question into one of:
  - {"type": "stock",     "ticker": "AAPL"}
  - {"type": "portfolio", "ticker": None}

Uses gpt-4o-mini for a cheap, fast single call. Falls back to "portfolio"
on any error so the main flow is never blocked.
"""
from __future__ import annotations

import json

from openai import OpenAI

from ..config import OPENAI_API_KEY

_ROUTER_SYSTEM = """\
You are a query classifier for a financial analyst assistant.

Given the user's question, return a JSON object with:
- "type": "stock" if the user is asking about a specific individual stock
  (e.g. whether to buy it, analysis of it, price target, should they add it).
  Otherwise "type": "portfolio".
- "ticker": the stock's Yahoo Finance ticker symbol in uppercase (e.g. "AAPL")
  if type is "stock", otherwise null.

Only return the JSON object, nothing else.

Examples:
  "Is MU worth adding?"            -> {"type": "stock", "ticker": "MU"}
  "Should I buy Apple stock?"      -> {"type": "stock", "ticker": "AAPL"}
  "Analyze NVIDIA for me"          -> {"type": "stock", "ticker": "NVDA"}
  "How does my portfolio look?"    -> {"type": "portfolio", "ticker": null}
  "What's the market doing today?" -> {"type": "portfolio", "ticker": null}
"""


def classify_intent(question: str) -> dict:
    """Return {"type": "stock"|"portfolio", "ticker": str|None}."""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user", "content": question},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=64,
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "type": result.get("type", "portfolio"),
            "ticker": result.get("ticker") or None,
        }
    except Exception:
        return {"type": "portfolio", "ticker": None}
