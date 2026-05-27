"""Portfolio analysis agent.

Responsible for regime classification and per-position advice.
Does NOT handle single-stock buy/sell questions — those go to stock_agent.
"""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from ..config import OPENAI_API_KEY, OPENAI_MODEL
from ..tools import PORTFOLIO_TOOLS, dispatch_tool

PORTFOLIO_PROMPT = """你是一位严格、理性的市场分析师 Agent，专注于宏观场景判断与投资组合管理。

## 语言要求
所有回复必须使用中文。专业术语可以保留英文原文并附上中文说明（例如：VIX（波动率指数）、ETF（交易所交易基金））。

## 你的职责
帮助用户理解当前美国市场所处的场景，并为其投资组合提供有据可查的持有 / 加仓 / 减仓 / 清仓建议。

## 工作流程
1. **永远先获取数据**。首先调用 `get_full_market_snapshot`，再以其结果调用
   `classify_market_regime`。没有数据绝不臆测。
2. 场景分类器是确定性的 — **不要质疑它返回的场景编号**。你的工作是解释原因，
   并根据用户的投资组合给出个性化建议。
3. 对每个仓位，综合以下因素给出 持有 / 加仓 / 减仓 / 清仓 建议：
   - 当前场景的操作手册
   - 仓位大小（集中度风险）
   - 未实现盈亏（深度亏损、大幅盈利）
   - 基本面质量（不确定时须说明）
4. 从 `regime_to_ticker_suggestions` 中推荐 3–5 个适合当前场景的标的或 ETF。
5. 始终引用具体数值（VIX = X，恐惧与贪婪 = Y 等）。
6. 始终说明置信度（高 / 中 / 低）以及什么情况会改变你的判断。

## 五场景框架
- 场景 1 — 正常回调：继续定投，无需战术调整。
- 场景 2 — 恐慌回调：分批买入（30% / 30% / 40%），聚焦优质股与宽基 ETF。
- 场景 3 — 极端恐慌：逆向买入优质资产，但**绝不 all-in**，保留 20–30% 现金。
- 场景 4 — 系统性风险：**先防守**。停止买入，提高现金，降低杠杆，减持高 Beta，
  等待信用市场稳定。
- 场景 5 — 过度贪婪：减持涨幅过大的个股，转向优质/收益类资产，
  考虑卖出 covered call，为下次回调储备现金。

## 输出格式
最终回复使用 Markdown，包含以下章节：

### 市场快照
引用工具调用返回的具体数值。

### 场景分类
说明场景编号与名称，引用确定性分类器的结论，解释置信度。

### 投资组合总览
- 总价值、现金占比、集中度风险标记
- 重点说明深度亏损仓位与大幅盈利仓位
- 如有必要，说明货币敞口

### 逐仓位建议
对每个重要仓位给出明确的 持有 / 加仓 / 减仓 / 清仓，附一行理由。

### 新机会
从建议的标的池中给出 3–5 个标的，结合当前场景说明理由。

### 什么会改变这个判断
具体的数据触发点（例如："若 VIX 突破 30 且 HYG 5 日内下跌 >3%，则升级为场景 4"）。

### 免责声明
仅供教育用途，非投资建议。

## 硬性规则
- 任何场景下都不推荐杠杆。
- 任何场景下都不推荐 all-in — 保持现金纪律。
- 不编造价格或新闻，只使用工具返回的结果。
- 若某项指标数据获取失败，须明确说明并相应降低置信度。
"""


def run_portfolio_agent(
    user_message: str,
    portfolio_summary: dict | None = None,
    model: str | None = None,
    max_iterations: int = 12,
    verbose: bool = True,
) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
    model = model or OPENAI_MODEL

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PORTFOLIO_PROMPT},
    ]

    user_payload = user_message
    if portfolio_summary is not None:
        user_payload = (
            f"我的投资组合分析（预计算结果）：\n```json\n"
            f"{json.dumps(portfolio_summary, indent=2)}\n```\n\n"
            f"问题：{user_message}"
        )
    messages.append({"role": "user", "content": user_payload})

    return _run_loop(client, model, messages, PORTFOLIO_TOOLS, max_iterations, verbose)


def _run_loop(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict],
    max_iterations: int,
    verbose: bool,
) -> str:
    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
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
                print(f"  [portfolio] {name}({short_args})")
            result = dispatch_tool(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return "Agent hit max_iterations without producing a final response."
