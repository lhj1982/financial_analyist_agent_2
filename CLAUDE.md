# CLAUDE.md

## Project Context
A multi-agent financial analyst CLI that classifies the US market into 5 regimes and answers two types of questions: portfolio-level advice (hold/buy/sell per position) and single-stock investment analysis (Buy/Wait/Avoid with 4-dimension scoring). A lightweight LLM router dispatches each question to the right specialist agent.

**Stack:** Python 3.12 · OpenAI API · yfinance · rich · argparse · python-dotenv

**Architecture:**
```
user question
  └─ router (gpt-4o-mini)
       ├─ stock question  → stock_agent     (Quality/Valuation/Momentum/Regime Fit)
       └─ portfolio question → portfolio_agent (regime + per-position advice)

src/agents/   router, portfolio_agent, stock_agent
src/agent.py  orchestrator (routes; main.py only ever calls run_agent() here)
src/tools.py  OpenAI tool schemas + DISPATCH + PORTFOLIO_TOOLS + STOCK_TOOLS
src/data_sources.py  all yfinance/HTTP fetchers with in-process TTL cache
src/regime.py        deterministic 5-scenario classifier (no LLM)
src/portfolio.py     portfolio loader + value/weight/PnL analyzer
src/config.py        env vars, ticker map, thresholds
src/main.py          CLI entry point (argparse + rich)
```

---

## Build & Run

```bash
# First-time setup
cp .env.example .env                      # add OPENAI_API_KEY (required)
cp portfolio.example.json portfolio.json  # fill in your holdings
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# CLI
python -m src.main snapshot          # raw market data — no LLM
python -m src.main regime            # deterministic regime classification — no LLM
python -m src.main portfolio         # display portfolio table — no LLM
python -m src.main analyze           # full portfolio LLM analysis
python -m src.main ask "Is MU worth adding?"       # auto-routes to stock agent
python -m src.main ask "How does my portfolio look?" # auto-routes to portfolio agent

# Shared flags (analyze / ask)
--portfolio PATH   # default: portfolio.json
--model MODEL      # override OPENAI_MODEL in .env
--quiet            # suppress tool-call logs
```

No test suite or linter configured yet.

---

## Code Conventions

- **Language:** All LLM system prompts and agent output must be in Chinese. Code and comments in English.
- **Data fetchers:** All yfinance/HTTP calls live in `data_sources.py`, return plain `dict`, and must use the `_cached(key, fetcher)` helper.
- **Tools registration:** Every new fetcher needs an entry in `TOOLS` (JSON schema) and `DISPATCH` in `tools.py`, and must be added to `PORTFOLIO_TOOLS`, `STOCK_TOOLS`, or both.
- **Naming:** `snake_case` everywhere. Tool function names must exactly match their `data_sources.py` counterpart.
- **No business logic in agents:** Regime rules → `regime.py`. Data math → `data_sources.py`. Agents only call tools and synthesize.
- **Comments:** Only for non-obvious *why*, never for *what*.

---

## Repo-Specific Rules

**Never modify or commit:**
| File | Reason |
|------|--------|
| `.env` | API keys — gitignored |
| `portfolio.json` | Real personal holdings — gitignored |

Use `portfolio.example.json` for safe examples. Both files are already in `.gitignore`.

---

## Common Tasks

**Add a new market data tool:**
1. Add fetcher function to `data_sources.py` (use `_cached`)
2. Add JSON schema entry to `TOOLS` list in `tools.py`
3. Add to `DISPATCH` map in `tools.py`
4. Add to `PORTFOLIO_TOOLS`, `STOCK_TOOLS`, or both depending on which agents need it
5. Reference the new tool in the relevant agent's system prompt

**Add a new agent:**
1. Create `src/agents/<name>_agent.py` with a `PROMPT` constant and `run_<name>_agent()` function using the existing loop pattern from `portfolio_agent.py`
2. Define a filtered tool list (like `STOCK_TOOLS`) in `tools.py`
3. Add a new intent type to `router.py` and dispatch it in `agent.py`

---

## Gotchas

- **yfinance `info["trailingPE"]` and `info["marketCap"]` are unreliable** — they return stale or mismatched values. Always compute P/E as `last_price / trailingEps` and use `fast_info.market_cap` for market cap instead.
- **`market_cap` must be formatted as a string** (e.g. `"$1.01T"`) before passing to the LLM. A raw number like `1010.31` in a field named `market_cap_bn` causes the LLM to misread it as "$101B".
- **`pe_forward` is not "the" P/E** — for high-growth stocks (e.g. MU in a memory upcycle), forward P/E can be dramatically lower than trailing. Always surface `pe_trailing` first in the brief; `pe_forward` is supplementary.
- **The in-process cache resets between CLI invocations.** There is no persistent cache. Each `python -m src.main ask` call re-fetches everything from yfinance.
- **`cmd_analyze` in `main.py` bypasses the router** — it calls `run_portfolio_agent` directly. Only `cmd_ask` goes through the router.
