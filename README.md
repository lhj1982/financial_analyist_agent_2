# Market Analyst Agent

A rational, rules-driven AI market analyst built with the OpenAI SDK.

It classifies the current US market regime into one of five scenarios
(normal pullback / panic pullback / extreme panic / systemic risk / excessive
greed) and gives **hold / buy / sell / rotate** suggestions tailored to your
portfolio.

## Framework

| Scenario | VIX | Fear & Greed | Pullback | Credit/Macro | Action |
|---|---|---|---|---|---|
| 1. Normal Pullback | 18–25 | 25–45 | -3% to -5% | Stable | Continue DCA |
| 2. Panic Pullback | >25, near 30 | <25 | -7% to -10% | HYG OK, USD calm | Batch buy 30/30/40 |
| 3. Extreme Panic | >35–40 | 0–15 | Deep | Credit & banks OK | Contrarian quality buys |
| 4. Systemic Risk | High, no retreat | — | — | Credit spreads blowing out, USD surging, banks crashing | **Defend** — raise cash |
| 5. Excessive Greed | <15 long-term | >75 | Index ATH, breadth weak | High valuations, leverage | Trim, rotate, sell calls |

## Setup

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# 4. Edit portfolio.json with your real positions
cp portfolio.example.json portfolio.json
# Edit portfolio.json
```

## Usage

```bash
# Quick market snapshot (no LLM call, fast)
python -m src.main snapshot

# Classify current regime (no LLM call)
python -m src.main regime

# Analyze portfolio with full LLM agent
python -m src.main analyze

# Ask a custom question
python -m src.main ask "Should I trim NVDA given the current regime?"

# Use a different portfolio file
python -m src.main analyze --portfolio path/to/other.json
```

## Project Layout

```
.
├── .env.example
├── portfolio.example.json
├── requirements.txt
├── README.md
└── src/
    ├── __init__.py
    ├── config.py          # Env vars, constants
    ├── data_sources.py    # yfinance, CNN F&G, FRED data fetchers
    ├── regime.py          # 5-scenario classifier (deterministic rules)
    ├── portfolio.py       # Portfolio analyzer
    ├── tools.py           # OpenAI function-calling tool definitions
    ├── agent.py           # OpenAI agent loop
    └── main.py            # CLI entry point
```

## Design Principles

1. **Rules before LLM** — regime classification is deterministic. The LLM
   synthesizes and personalizes, never invents the regime.
2. **Credit market is the truth-teller** — the S3 vs S4 distinction
   (opportunity vs danger) hinges on credit health.
3. **Always show the work** — every recommendation cites the numbers behind it.
4. **Educational only** — not financial advice.
