"""Orchestrator — routes questions to the right specialist agent.

main.py still calls run_agent(); this module just decides which agent to use.
"""
from __future__ import annotations

from .agents.router import classify_intent
from .agents.portfolio_agent import run_portfolio_agent
from .agents.stock_agent import run_stock_agent
from .config import OPENAI_API_KEY


def run_agent(
    user_message: str,
    portfolio_summary: dict | None = None,
    model: str | None = None,
    max_iterations: int = 12,
    verbose: bool = True,
) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    intent = classify_intent(user_message)
    if verbose:
        tag = f"stock:{intent['ticker']}" if intent["type"] == "stock" else "portfolio"
        print(f"  [router] → {tag}")

    if intent["type"] == "stock":
        return run_stock_agent(
            user_message=user_message,
            ticker=intent.get("ticker"),
            portfolio_summary=portfolio_summary,
            model=model,
            max_iterations=max_iterations,
            verbose=verbose,
        )

    return run_portfolio_agent(
        user_message=user_message,
        portfolio_summary=portfolio_summary,
        model=model,
        max_iterations=max_iterations,
        verbose=verbose,
    )
