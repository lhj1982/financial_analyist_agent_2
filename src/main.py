"""CLI entry point.

Usage:
    python -m src.main snapshot                    # raw market snapshot, no LLM
    python -m src.main regime                      # classify regime, no LLM
    python -m src.main portfolio                   # analyze portfolio only
    python -m src.main analyze                     # full LLM analysis
    python -m src.main ask "your question here"    # custom LLM question

Options:
    --portfolio PATH      path to portfolio JSON (default: portfolio.json)
    --model MODEL         override OPENAI_MODEL
    --quiet               suppress tool-call logs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from . import data_sources, portfolio as portfolio_mod, regime as regime_mod
from .agent import run_agent
from .config import DEFAULT_PORTFOLIO_PATH

console = Console()


def _print_json(title: str, data) -> None:
    console.print(Panel.fit(title, style="bold cyan"))
    console.print_json(data=data)
    console.print()


def cmd_snapshot(_args) -> int:
    console.print("[bold]Fetching market snapshot...[/bold]\n")
    snap = data_sources.get_full_market_snapshot()
    _print_json("Market Snapshot", snap)
    return 0


def cmd_regime(_args) -> int:
    console.print("[bold]Fetching market data...[/bold]")
    snap = data_sources.get_full_market_snapshot()
    console.print("[bold]Classifying regime...[/bold]\n")
    regime = regime_mod.classify_regime(snap)

    s = regime["scenario"]
    name = regime["name"]
    color = {0: "white", 1: "green", 2: "yellow", 3: "orange1", 4: "red", 5: "magenta"}[s]
    console.print(Panel.fit(
        f"[bold {color}]Scenario {s}: {name}[/bold {color}]\n"
        f"Confidence: {regime['confidence']}",
        title="Regime"
    ))

    console.print("\n[bold]Reasoning:[/bold]")
    for r in regime["reasoning"]:
        console.print(f"  • {r}")

    console.print("\n[bold]Action Summary:[/bold]")
    console.print(f"  {regime['playbook']['action_summary']}")

    console.print("\n[bold]Tactics:[/bold]")
    for t in regime["playbook"]["tactics"]:
        console.print(f"  • {t}")

    console.print("\n[bold]Signals Used:[/bold]")
    sig_table = Table(show_header=True, header_style="bold")
    sig_table.add_column("Signal")
    sig_table.add_column("Value", justify="right")
    for k, v in regime["signals_used"].items():
        sig_table.add_row(k, str(v))
    console.print(sig_table)

    suggestions = regime_mod.regime_to_ticker_suggestions(regime)
    console.print("\n[bold]Preferred Buckets:[/bold]")
    console.print_json(data=suggestions["preferred"])
    console.print("\n[bold]Avoid Buckets:[/bold]")
    console.print_json(data=suggestions["avoid"])
    return 0


def cmd_portfolio(args) -> int:
    path = Path(args.portfolio)
    if not path.exists():
        console.print(f"[red]Portfolio file not found: {path}[/red]")
        console.print(f"Tip: cp portfolio.example.json {path}")
        return 1

    portfolio = portfolio_mod.load_portfolio(path)
    console.print(f"[bold]Analyzing portfolio: {path}[/bold]\n")
    summary = portfolio_mod.analyze_portfolio(portfolio)

    # Pretty summary table
    table = Table(title="Positions", show_header=True, header_style="bold")
    table.add_column("Ticker")
    table.add_column("Cat")
    table.add_column("Shares", justify="right")
    table.add_column("Buy", justify="right")
    table.add_column("Last", justify="right")
    table.add_column("PnL %", justify="right")
    table.add_column("Weight %", justify="right")
    for p in summary["positions"]:
        pnl = p.get("unrealized_pnl_pct")
        pnl_str = f"{pnl:+.2f}" if pnl is not None else "—"
        pnl_style = "green" if pnl and pnl > 0 else ("red" if pnl and pnl < 0 else "white")
        table.add_row(
            p.get("ticker", "?"),
            p.get("category", "?"),
            str(p.get("shares") or "—"),
            str(p.get("buy_price") or "—"),
            str(p.get("last_price") or p.get("value_sek") or "—"),
            f"[{pnl_style}]{pnl_str}[/{pnl_style}]",
            f"{p.get('portfolio_weight_pct', 0):.2f}",
        )
    console.print(table)

    console.print(f"\n[bold]Total value (est):[/bold] {summary['total_value_estimate']:,.2f}")
    console.print(f"[bold]Cash:[/bold] {summary['cash']:,.2f}  "
                  f"([cyan]{summary['cash_pct']:.2f}%[/cyan])")
    console.print(f"[bold]Value by currency:[/bold] {summary['value_by_currency']}")

    if summary["flags"]:
        console.print("\n[bold red]Risk Flags:[/bold red]")
        for f in summary["flags"]:
            console.print(f"  ⚠ {f}")

    if summary["deep_losers"]:
        console.print("\n[bold]Deep losers (< -20%):[/bold]")
        for p in summary["deep_losers"]:
            console.print(f"  • {p['ticker']}: {p['pnl_pct']:+.2f}%")

    if summary["big_winners"]:
        console.print("\n[bold]Big winners (> +20%):[/bold]")
        for p in summary["big_winners"]:
            console.print(f"  • {p['ticker']}: {p['pnl_pct']:+.2f}%")
    return 0


def cmd_analyze(args) -> int:
    path = Path(args.portfolio)
    if not path.exists():
        console.print(f"[red]Portfolio file not found: {path}[/red]")
        return 1

    portfolio = portfolio_mod.load_portfolio(path)
    console.print(f"[bold]Analyzing portfolio: {path}[/bold]\n")
    summary = portfolio_mod.analyze_portfolio(portfolio)

    console.print("[bold]Calling agent (this may take ~30s for tool calls)...[/bold]\n")
    answer = run_agent(
        user_message=(
            "Please assess the current market regime, review my portfolio, and "
            "give per-position recommendations plus 3-5 new opportunities."
        ),
        portfolio_summary=summary,
        model=args.model,
        verbose=not args.quiet,
    )
    console.print()
    console.print(Markdown(answer))
    return 0


def cmd_ask(args) -> int:
    portfolio_summary = None
    path = Path(args.portfolio)
    if path.exists():
        portfolio = portfolio_mod.load_portfolio(path)
        portfolio_summary = portfolio_mod.analyze_portfolio(portfolio)

    console.print(f"[bold]Question:[/bold] {args.question}\n")
    answer = run_agent(
        user_message=args.question,
        portfolio_summary=portfolio_summary,
        model=args.model,
        verbose=not args.quiet,
    )
    console.print()
    console.print(Markdown(answer))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="market-analyst",
        description="AI Market Analyst — regime-aware portfolio advisor",
    )
    p.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO_PATH),
                   help="Path to portfolio JSON (default: portfolio.json)")
    p.add_argument("--model", default=None, help="Override OPENAI_MODEL")
    p.add_argument("--quiet", action="store_true", help="Suppress tool-call logs")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="Print raw market snapshot (no LLM)")
    sub.add_parser("regime", help="Classify current regime (no LLM)")
    sub.add_parser("portfolio", help="Analyze portfolio (no LLM)")
    sub.add_parser("analyze", help="Full LLM analysis of portfolio + regime")

    ask = sub.add_parser("ask", help="Ask the agent a custom question")
    ask.add_argument("question", help="Question to ask")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cmd = args.command
    handlers = {
        "snapshot": cmd_snapshot,
        "regime": cmd_regime,
        "portfolio": cmd_portfolio,
        "analyze": cmd_analyze,
        "ask": cmd_ask,
    }
    try:
        return handlers[cmd](args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return 130
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if not args.quiet:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
