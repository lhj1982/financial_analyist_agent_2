"""Single-stock investment analysis agent.

Answers questions like "Is MU worth adding?" by combining:
  1. Market regime context (get_full_market_snapshot + classify_market_regime)
  2. Stock-specific deep dive (get_stock_analysis)
  3. Current price quote (get_ticker_quote)

The agent scores the stock on four dimensions (Quality / Valuation /
Momentum / Regime Fit) and gives a clear Buy / Wait / Avoid verdict.
"""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from ..config import OPENAI_API_KEY, OPENAI_MODEL
from ..tools import STOCK_TOOLS, dispatch_tool

STOCK_PROMPT = """你是一位严格、理性的个股研究 Agent，专注于单只股票的投资价值评估。

## 语言要求
所有回复必须使用中文。专业术语可以保留英文原文并附上中文说明。

## 你的职责
基于市场场景和股票基本面/技术面数据，判断一只股票是否值得买入或加仓，
并给出有据可查的具体建议。

## 工作流程
1. 调用 `get_full_market_snapshot`，再调用 `classify_market_regime`，确定当前市场场景。
2. 调用 `get_stock_analysis(ticker)` 获取目标股票的完整分析数据。
3. 从以下四个维度逐一评分（高 / 中 / 低），并附一句关键理由：

   | 维度 | 关键指标 |
   |------|---------|
   | **质量** | 毛利率、净利率、ROE、负债率、自由现金流 |
   | **估值** | **滚动 P/E（`pe_trailing`）** 为主，前瞻 P/E（`pe_forward`）为辅；P/S、P/B；分析师目标价上行空间 |
   | **动量** | RSI-14、价格 vs MA50/MA200、5d/20d/60d 涨跌幅 |
   | **场景适配** | Beta 与当前场景匹配度、行业在该场景中的表现预期 |

4. 综合四维给出明确结论：**买入 / 观望（等待回调至 X 价位）/ 回避**，
   附具体入场条件和建议仓位（占投资组合比例）。
5. 若用户提供了投资组合，还需评估：集中度变化、与现有仓位的相关性、
   是否重复暴露同一行业。

## 输出格式（Markdown）

### 市场快照
引用具体数值（VIX、恐惧贪婪指数、场景编号）。

### 股票概况
名称、行业、**当前股价**（引用 `current_price` 字段）、
市值（引用 `market_cap` 字段，例如 "$1.01T"）、Beta、
**滚动 P/E**（引用 `pe_trailing`）、前瞻 P/E（引用 `pe_forward`）。

### 四维评分
每个维度一行：评分（高/中/低）+ 一句关键数据支撑。

### 综合建议
**买入 / 观望 / 回避** — 附：
- 入场价位或触发条件
- 建议仓位（% of portfolio）
- 止损参考

### 风险提示
最多 3 条关键下行风险。

### 什么会改变这个判断
具体的数据触发点（例如："若 pe_forward 升破 20 且 RSI > 75，则评级降为观望"）。

### 免责声明
仅供教育用途，非投资建议。

## 硬性规则
- 任何场景下都不推荐杠杆。
- 不编造价格或新闻，只使用工具返回的结果。
- 若某项指标数据获取失败，须明确说明并相应降低置信度。
- 估值评分必须优先引用 `pe_trailing`（滚动市盈率），再辅以 `pe_forward`。
"""


def run_stock_agent(
    user_message: str,
    ticker: str | None = None,
    portfolio_summary: dict | None = None,
    model: str | None = None,
    max_iterations: int = 10,
    verbose: bool = True,
) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
    model = model or OPENAI_MODEL

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": STOCK_PROMPT},
    ]

    # Build user payload — inject ticker and optional portfolio context
    parts: list[str] = []
    if ticker:
        parts.append(f"目标股票代码：**{ticker.upper()}**")
    if portfolio_summary is not None:
        parts.append(
            f"我的投资组合分析（预计算结果）：\n```json\n"
            f"{json.dumps(portfolio_summary, indent=2)}\n```"
        )
    parts.append(f"问题：{user_message}")
    messages.append({"role": "user", "content": "\n\n".join(parts)})

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=STOCK_TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if not msg.tool_calls:
            return msg.content or ""

        for tc in msg.tool_calls:
            name = tc.function.name
            args = tc.function.arguments
            if verbose:
                short_args = args if len(args) < 120 else args[:117] + "..."
                print(f"  [stock] {name}({short_args})")
            result = dispatch_tool(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return "Agent hit max_iterations without producing a final response."
