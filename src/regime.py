"""Deterministic 5-scenario regime classifier.

Order matters: Scenario 4 (systemic risk) is checked FIRST because it can
overlap with S2/S3 and represents the most important "don't catch the knife"
signal.
"""
from __future__ import annotations

from typing import Any

from .config import THRESHOLDS, TICKER_UNIVERSE


SCENARIO_PLAYBOOK = {
    1: {
        "name": "Normal Pullback",
        "action_summary": "Continue DCA at planned cadence.",
        "tactics": [
            "Stick to monthly contributions to broad index funds.",
            "Do NOT increase position size or use leverage.",
            "Re-check breadth and credit weekly.",
        ],
        "preferred_buckets": ["core_etfs"],
        "avoid_buckets": ["high_beta_avoid_in_s4"],
        "cash_target_pct": 5,
    },
    2: {
        "name": "Panic Pullback — Batch Buy",
        "action_summary": "Begin staged buying: 30% / 30% / 40%.",
        "tactics": [
            "1st 30% now (VIX > 25).",
            "2nd 30% if VIX reaches ~30.",
            "Final 40% once VIX rolls over from peak AND breadth improves.",
            "Focus on quality and broad ETFs.",
        ],
        "preferred_buckets": ["core_etfs", "quality_growth"],
        "avoid_buckets": ["high_beta_avoid_in_s4"],
        "cash_target_pct": 5,
    },
    3: {
        "name": "Extreme Panic — Contrarian Opportunity",
        "action_summary": "Buy quality, but DO NOT all-in. Keep dry powder.",
        "tactics": [
            "Buy core market ETFs (SPY/VOO/RSP).",
            "Add quality compounders with strong cash flow.",
            "Avoid leveraged or unprofitable names.",
            "Keep 20-30% in cash for further drawdowns.",
        ],
        "preferred_buckets": ["core_etfs", "quality_growth", "defensive"],
        "avoid_buckets": ["high_beta_avoid_in_s4"],
        "cash_target_pct": 20,
    },
    4: {
        "name": "Systemic Risk — Defend First",
        "action_summary": "STOP buying. Raise cash, cut leverage, trim high-beta.",
        "tactics": [
            "Do NOT bottom-fish — credit markets must stabilize first.",
            "Reduce leverage to zero.",
            "Trim high-beta and unprofitable names.",
            "Rotate to defensives and safe havens.",
            "Hold cash. Wait for credit spreads to retreat and VIX to roll over.",
        ],
        "preferred_buckets": ["defensive", "safe_haven"],
        "avoid_buckets": ["high_beta_avoid_in_s4", "quality_growth"],
        "cash_target_pct": 30,
    },
    5: {
        "name": "Excessive Greed — Reduce Aggressiveness",
        "action_summary": "Trim winners, rotate to quality / income, sell covered calls.",
        "tactics": [
            "Sell positions that have run too far above your target weights.",
            "Rotate gains into core and income ETFs.",
            "Consider covered calls on big winners.",
            "Raise some cash for the next pullback.",
        ],
        "preferred_buckets": ["income_in_s5", "defensive", "core_etfs"],
        "avoid_buckets": ["high_beta_avoid_in_s4"],
        "cash_target_pct": 15,
    },
    0: {
        "name": "Neutral / No Clear Signal",
        "action_summary": "No regime trigger. Maintain plan, monitor.",
        "tactics": [
            "Continue planned contributions.",
            "Do not make tactical moves without a clear signal.",
            "Re-check indicators weekly.",
        ],
        "preferred_buckets": ["core_etfs"],
        "avoid_buckets": [],
        "cash_target_pct": 10,
    },
}


def _safe(d: dict | None, key: str, default=None):
    if not d or not isinstance(d, dict):
        return default
    v = d.get(key, default)
    return default if v is None else v


def classify_regime(snapshot: dict) -> dict:
    """Apply rules to classify market state into Scenario 0–5.

    `snapshot` is the dict returned by `data_sources.get_full_market_snapshot()`.
    Returns a structured classification with reasoning.
    """
    t = THRESHOLDS
    vol = snapshot.get("volatility") or {}
    fg = snapshot.get("fear_greed") or {}
    credit = snapshot.get("credit") or {}
    macro = snapshot.get("macro") or {}
    breadth = snapshot.get("breadth") or {}
    pullback = snapshot.get("pullback") or {}
    banks = snapshot.get("banks") or {}

    vix = _safe(vol, "vix")
    move = _safe(vol, "move_index")
    fg_value = _safe(fg, "value")
    hyg_5d = _safe(credit, "hyg_5d_change_pct")
    jnk_5d = _safe(credit, "jnk_5d_change_pct")
    dxy_20d = _safe(macro, "dxy_20d_change_pct")
    spy_pullback = _safe(pullback, "spy_drawdown_pct")
    kbe_5d = _safe(banks, "kbe_5d_change_pct")
    kre_5d = _safe(banks, "kre_5d_change_pct")
    breadth_trend = _safe(breadth, "breadth_ratio_trend_pct")

    signals_used = {
        "vix": vix,
        "fear_greed": fg_value,
        "spy_drawdown_pct": spy_pullback,
        "hyg_5d_change_pct": hyg_5d,
        "jnk_5d_change_pct": jnk_5d,
        "dxy_20d_change_pct": dxy_20d,
        "kbe_5d_change_pct": kbe_5d,
        "kre_5d_change_pct": kre_5d,
        "move_index": move,
        "breadth_trend_pct": breadth_trend,
    }
    reasons: list[str] = []

    # ---- Scenario 4: Systemic risk (check FIRST) ----
    systemic_flags = 0
    s4_reasons = []
    if hyg_5d is not None and hyg_5d <= t["s4_hyg_5d_drop"]:
        systemic_flags += 1
        s4_reasons.append(f"HYG fell {hyg_5d:.2f}% in 5d (<= {t['s4_hyg_5d_drop']}%).")
    if dxy_20d is not None and dxy_20d >= t["s4_dxy_20d_surge"]:
        systemic_flags += 1
        s4_reasons.append(f"USD surged {dxy_20d:.2f}% in 20d (>= {t['s4_dxy_20d_surge']}%).")
    if kbe_5d is not None and kbe_5d <= t["s4_bank_5d_drop"]:
        systemic_flags += 1
        s4_reasons.append(f"Bank ETF KBE fell {kbe_5d:.2f}% in 5d (<= {t['s4_bank_5d_drop']}%).")
    if move is not None and move >= t["s4_move_high"]:
        systemic_flags += 1
        s4_reasons.append(f"MOVE index at {move:.1f} (>= {t['s4_move_high']}) — Treasury vol stressed.")

    if systemic_flags >= 2 and vix is not None and vix >= t["s4_vix_floor"]:
        return {
            "scenario": 4,
            "confidence": "high" if systemic_flags >= 3 else "medium",
            "name": SCENARIO_PLAYBOOK[4]["name"],
            "playbook": SCENARIO_PLAYBOOK[4],
            "reasoning": [
                f"Systemic flags triggered: {systemic_flags}.",
                f"VIX {vix:.2f} >= {t['s4_vix_floor']}.",
            ] + s4_reasons,
            "signals_used": signals_used,
        }

    # ---- Scenario 3: Extreme panic (with credit OK) ----
    if (
        vix is not None and vix >= t["s3_vix_min"]
        and fg_value is not None and fg_value <= t["s3_fg_max"]
    ):
        reasons = [
            f"VIX {vix:.2f} >= {t['s3_vix_min']}.",
            f"Fear & Greed {fg_value} <= {t['s3_fg_max']} (extreme fear).",
        ]
        return {
            "scenario": 3,
            "confidence": "high",
            "name": SCENARIO_PLAYBOOK[3]["name"],
            "playbook": SCENARIO_PLAYBOOK[3],
            "reasoning": reasons,
            "signals_used": signals_used,
        }

    # ---- Scenario 2: Panic pullback ----
    if (
        vix is not None and vix > t["s2_vix_low"]
        and (fg_value is None or fg_value <= t["s2_fg_max"])
        and spy_pullback is not None and spy_pullback <= t["s2_pullback_max"]
    ):
        reasons = [
            f"VIX {vix:.2f} > {t['s2_vix_low']}.",
            f"SPY drawdown {spy_pullback:.2f}% <= {t['s2_pullback_max']}%.",
        ]
        if fg_value is not None:
            reasons.append(f"Fear & Greed {fg_value} <= {t['s2_fg_max']}.")
        return {
            "scenario": 2,
            "confidence": "high",
            "name": SCENARIO_PLAYBOOK[2]["name"],
            "playbook": SCENARIO_PLAYBOOK[2],
            "reasoning": reasons,
            "signals_used": signals_used,
        }

    # ---- Scenario 5: Excessive greed ----
    if (
        vix is not None and vix < t["s5_vix_max"]
        and fg_value is not None and fg_value >= t["s5_fg_min"]
    ):
        reasons = [
            f"VIX {vix:.2f} < {t['s5_vix_max']} (complacency).",
            f"Fear & Greed {fg_value} >= {t['s5_fg_min']} (extreme greed).",
        ]
        if breadth_trend is not None and breadth_trend < 0:
            reasons.append(
                f"Breadth narrowing ({breadth_trend:.2f}% RSP/SPY 20d) — confirms late-cycle behavior."
            )
        return {
            "scenario": 5,
            "confidence": "high" if breadth_trend is not None and breadth_trend < 0 else "medium",
            "name": SCENARIO_PLAYBOOK[5]["name"],
            "playbook": SCENARIO_PLAYBOOK[5],
            "reasoning": reasons,
            "signals_used": signals_used,
        }

    # ---- Scenario 1: Normal pullback ----
    if (
        vix is not None and t["s1_vix_low"] <= vix <= t["s1_vix_high"]
        and (fg_value is None or t["s1_fg_low"] <= fg_value <= t["s1_fg_high"])
        and spy_pullback is not None
        and t["s1_pullback_min"] <= spy_pullback <= t["s1_pullback_max"]
    ):
        reasons = [
            f"VIX {vix:.2f} in [{t['s1_vix_low']}, {t['s1_vix_high']}].",
            f"SPY drawdown {spy_pullback:.2f}% in [{t['s1_pullback_min']}, {t['s1_pullback_max']}].",
        ]
        if fg_value is not None:
            reasons.append(f"Fear & Greed {fg_value} in [{t['s1_fg_low']}, {t['s1_fg_high']}].")
        return {
            "scenario": 1,
            "confidence": "medium",
            "name": SCENARIO_PLAYBOOK[1]["name"],
            "playbook": SCENARIO_PLAYBOOK[1],
            "reasoning": reasons,
            "signals_used": signals_used,
        }

    # ---- Default: Neutral ----
    return {
        "scenario": 0,
        "confidence": "low",
        "name": SCENARIO_PLAYBOOK[0]["name"],
        "playbook": SCENARIO_PLAYBOOK[0],
        "reasoning": [
            "No scenario thresholds triggered.",
            f"VIX={vix}, F&G={fg_value}, SPY pullback={spy_pullback}.",
        ],
        "signals_used": signals_used,
    }


def regime_to_ticker_suggestions(regime: dict, max_per_bucket: int = 3) -> dict[str, list[str]]:
    """Map a classified regime to suggested ticker buckets."""
    playbook = regime.get("playbook", {})
    preferred = playbook.get("preferred_buckets", [])
    avoid = playbook.get("avoid_buckets", [])

    return {
        "preferred": {
            b: TICKER_UNIVERSE.get(b, [])[:max_per_bucket] for b in preferred
        },
        "avoid": {
            b: TICKER_UNIVERSE.get(b, [])[:max_per_bucket] for b in avoid
        },
    }
