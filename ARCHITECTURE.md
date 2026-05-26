# 系统架构与算法说明

> 本文档详细说明市场分析师 Agent 的设计思路、数据流、核心算法及各模块职责。

---

## 目录

1. [设计哲学](#1-设计哲学)
2. [系统总览](#2-系统总览)
3. [模块说明](#3-模块说明)
4. [核心算法：五场景分类器](#4-核心算法五场景分类器)
5. [数据层](#5-数据层)
6. [Agent 工作流程](#6-agent-工作流程)
7. [投资组合分析器](#7-投资组合分析器)
8. [信号解读指南](#8-信号解读指南)
9. [已知局限与后续改进](#9-已知局限与后续改进)

---

## 1. 设计哲学

本系统遵循一条核心原则：

> **规则决定场景，LLM 负责解释。**

市场场景由确定性规则计算得出，LLM（大语言模型）只做综合分析与个性化表达，绝不参与数值判断。理由如下：

| 任务 | 用规则 | 用 LLM |
|---|---|---|
| "VIX > 35 且 F&G < 15 是极端恐慌吗？" | ✅ 精确、可重复 | ❌ 可能幻觉或前后不一致 |
| "结合我的仓位，这意味着什么？" | ❌ 过于复杂 | ✅ 语言综合，最擅长 |
| "给我推荐3个标的并解释理由" | ❌ 不能自动推理 | ✅ 结合上下文推理 |

这种**混合架构**（规则 + LLM）比纯 LLM 方式更可靠，也比纯规则方式更灵活。

---

## 2. 系统总览

```
用户输入（CLI 命令 + 投资组合 JSON）
           │
           ▼
┌─────────────────────┐
│   main.py (CLI)     │  解析命令，路由到对应处理函数
└──────────┬──────────┘
           │
     ┌─────┴──────────────────────────────┐
     │                                    │
     ▼                                    ▼
┌─────────────┐                  ┌────────────────┐
│ portfolio.py│                  │   agent.py     │
│ 投资组合分析│                  │  OpenAI 循环   │
└──────┬──────┘                  └───────┬────────┘
       │                                 │
       │              ┌──────────────────┤
       │              │   tools.py       │  工具调度器
       │              │  （11个工具）    │
       │              └──────┬───────────┘
       │                     │
       │         ┌───────────┴──────────────┐
       │         ▼                          ▼
       │  ┌─────────────┐         ┌──────────────────┐
       │  │data_sources │         │   regime.py      │
       │  │ 数据获取层  │         │  场景分类器      │
       │  └──────┬──────┘         └──────────────────┘
       │         │
       │    ┌────┴─────────────────────────────┐
       │    │            外部数据源             │
       │    │     yfinance | CNN F&G            │
       │    └──────────────────────────────────┘
       │
       └──────────────► 最终 Markdown 输出
```

---

## 3. 模块说明

### `src/config.py` — 配置与常量

所有可调参数集中于此，无需改动业务逻辑。

**环境变量**（来自 `.env`）：

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ 是 | — | OpenAI API 密钥 |
| `OPENAI_MODEL` | 否 | `gpt-4o` | 使用的模型，可改为 `o1`、`o3-mini` 等 |
| `DATA_CACHE_TTL` | 否 | `300` | 市场数据缓存时间（秒） |

**场景阈值**（可直接在文件中调整）：

```python
THRESHOLDS = {
    "s1_vix_low": 18.0,    # 场景 1：VIX 下界
    "s1_vix_high": 25.0,   # 场景 1：VIX 上界
    "s3_vix_min": 35.0,    # 场景 3：触发阈值
    "s4_hyg_5d_drop": -3.0,# 场景 4：HYG 5日跌幅警戒线
    ...
}
```

**修改建议**：如果你的风险偏好更保守，可以将 `s2_vix_low` 从 25 调低至 22，更早触发分批买入。

---

### `src/data_sources.py` — 数据获取层

负责从外部数据源拉取所有市场指标，并做本地 TTL 缓存（默认 5 分钟）。

**缓存机制**：

```python
_cache: dict[str, tuple[float, Any]] = {}

def _cached(key, fetcher, ttl=300):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]     # 命中缓存
    value = fetcher()
    _cache[key] = (now, value)    # 写入缓存
    return value
```

目的：同一次 `analyze` 命令中多个工具调用同一 ticker 时，不重复请求 yfinance。

**数据源清单**：

| 数据 | 来源 | 说明 |
|---|---|---|
| VIX | yfinance `^VIX` | 30日隐含波动率 |
| MOVE 指数 | yfinance `^MOVE` | 债券市场波动率，可能不可用 |
| SPY / RSP / IWM / QQQ | yfinance | 大盘广度 |
| HYG / JNK / LQD | yfinance | 信用市场健康度 |
| DXY（美元指数） | yfinance `DX-Y.NYB` | 全球避险需求 |
| 10年期美债收益率 | yfinance `^TNX` | 利率水平（原始值需 ÷10） |
| 黄金 / TLT | yfinance | 避险资产 |
| KBE / KRE | yfinance | 银行板块压力 |
| 恐惧与贪婪指数 | CNN 非官方 JSON API | 无需 API key |

**注意**：`^TNX` 的原始值是收益率的 10 倍（例如 42.0 代表 4.2%），`data_sources.py` 已自动 ÷10 处理。

---

### `src/regime.py` — 五场景分类器

见 [第 4 节](#4-核心算法五场景分类器)。

---

### `src/portfolio.py` — 投资组合分析器

见 [第 7 节](#7-投资组合分析器)。

---

### `src/tools.py` — OpenAI 工具调度器

定义了 11 个供 LLM 调用的工具，并将工具名称映射到对应的 Python 函数：

```python
DISPATCH = {
    "get_volatility_snapshot":    data_sources.get_volatility_snapshot,
    "get_fear_greed_index":       data_sources.get_fear_greed_index,
    "get_credit_market_health":   data_sources.get_credit_market_health,
    "get_macro_snapshot":         data_sources.get_macro_snapshot,
    "get_market_breadth":         data_sources.get_market_breadth,
    "get_index_pullback":         data_sources.get_index_pullback,
    "get_bank_stress":            data_sources.get_bank_stress,
    "get_full_market_snapshot":   data_sources.get_full_market_snapshot,
    "classify_market_regime":     regime.classify_regime,
    "get_ticker_quote":           data_sources.get_ticker_quote,
    "regime_to_ticker_suggestions": regime.regime_to_ticker_suggestions,
}
```

`dispatch_tool()` 负责：参数反序列化 → 调用函数 → 结果序列化为 JSON 字符串 → 返回给 LLM。

---

### `src/agent.py` — OpenAI Agent 循环

见 [第 6 节](#6-agent-工作流程)。

---

### `src/main.py` — CLI 入口

提供 5 个子命令：

| 命令 | 是否调用 LLM | 用途 |
|---|---|---|
| `snapshot` | 否 | 打印原始市场数据，验证数据源是否正常 |
| `regime` | 否 | 运行场景分类器，输出场景编号与操作建议 |
| `portfolio` | 否 | 分析投资组合盈亏与集中度 |
| `analyze` | **是** | 完整分析：市场 + 投资组合 + LLM 建议 |
| `ask "问题"` | **是** | 向 Agent 提自定义问题 |

**建议先跑三个无 LLM 命令确认数据正常，再跑 `analyze`**，节省 API 费用。

---

## 4. 核心算法：五场景分类器

这是整个系统最关键的部分。分类器是**纯确定性函数**，输入为市场指标字典，输出为场景编号（0–5）。

### 4.1 输入信号

```
snapshot = {
  "volatility": { "vix": 28.5, "move_index": 115.0, ... },
  "fear_greed": { "value": 22.0, "rating": "Extreme Fear", ... },
  "credit":     { "hyg_5d_change_pct": -1.2, "jnk_5d_change_pct": -1.5, ... },
  "macro":      { "dxy_20d_change_pct": 1.8, "yield_10y_pct": 4.35, ... },
  "breadth":    { "rsp_minus_spy_20d_pct": -3.2, ... },
  "pullback":   { "spy_drawdown_pct": -8.5, ... },
  "banks":      { "kbe_5d_change_pct": -2.1, ... }
}
```

### 4.2 分类逻辑（伪代码）

```
函数 classify_regime(snapshot):

  1. 收集系统性风险标志：
     如果 HYG 5日跌幅 ≤ -3%      → 系统性标志 +1
     如果 DXY 20日涨幅 ≥ +3%      → 系统性标志 +1
     如果 KBE 5日跌幅 ≤ -8%      → 系统性标志 +1
     如果 MOVE 指数 ≥ 140         → 系统性标志 +1

  2. 场景 4（最优先）：
     如果 系统性标志 ≥ 2 且 VIX ≥ 25
     → 返回 场景 4（系统性风险）

  3. 场景 3：
     如果 VIX ≥ 35 且 F&G ≤ 15
     → 返回 场景 3（极端恐慌）

  4. 场景 2：
     如果 VIX > 25 且 F&G ≤ 25 且 SPY回调 ≤ -7%
     → 返回 场景 2（恐慌回调）

  5. 场景 5：
     如果 VIX < 15 且 F&G ≥ 75
     → 返回 场景 5（过度贪婪）

  6. 场景 1：
     如果 18 ≤ VIX ≤ 25 且 25 ≤ F&G ≤ 45 且 -5% ≤ SPY回调 ≤ -3%
     → 返回 场景 1（正常回调）

  7. 默认：返回 场景 0（中性，无明确信号）
```

### 4.3 为什么场景 4 最先检查？

场景 4 会在 VIX 高企时与场景 2/3 产生重叠（例如 VIX=38，看起来像极端恐慌，但信用市场同时崩溃）。此时**系统性风险优先级最高**，必须防守，而不是买入。因此场景 4 的判断必须在 3 之前执行。

### 4.4 场景 3 vs 场景 4 的关键区分

这是整个框架中最重要的判断：

```
VIX 高 + F&G 低
      │
      ├── 信用市场正常（HYG 稳、DXY 平、银行股无崩盘）
      │   └──► 场景 3：极端恐慌 = 买入机会
      │
      └── 信用市场异常（≥2个系统性标志触发）
          └──► 场景 4：系统性风险 = 先防守
```

**信用市场是"说真话"的那个**。股票价格可以被情绪驱动，但机构信用交易员在用真金白银表态。当 HYG/JNK 大跌、信用利差快速扩大时，代表借贷条件正在恶化，系统性去杠杆风险真实存在。

### 4.5 场景置信度计算

| 条件 | 置信度 |
|---|---|
| 场景 4 且触发标志 ≥ 3 | 高 |
| 场景 4 且触发标志 = 2 | 中 |
| 场景 3、2（全部条件满足） | 高 |
| 场景 5 且广度同时恶化 | 高 |
| 场景 5 但广度数据缺失 | 中 |
| 场景 1（部分指标缺失） | 中 |
| 场景 0（无阈值触发） | 低 |

### 4.6 各场景操作手册

#### 场景 1：正常回调
- 继续按计划定投
- 不增加仓位，不使用杠杆
- 每周复查广度与信用

#### 场景 2：恐慌回调
- **第一笔 30%**：VIX > 25 时
- **第二笔 30%**：VIX 冲到 30 时
- **最后 40%**：VIX 从高位回落，市场广度改善时
- 聚焦优质股与宽基 ETF

#### 场景 3：极端恐慌
- 买入核心 ETF（SPY / VOO / RSP）
- 加仓强现金流的优质成长股
- 避免高杠杆或亏损型公司
- 保留 20–30% 现金备用

#### 场景 4：系统性风险
- 停止一切买入行为
- 杠杆归零
- 减持高 Beta 与弱资产负债表仓位
- 转向防御性资产与避险资产
- 等信用利差收窄、VIX 从高位回落

#### 场景 5：过度贪婪
- 卖出涨幅严重偏离目标仓位的个股
- 将盈利转入核心指数与收益型 ETF
- 对大赢家卖出 covered call
- 提高现金储备，为下次回调做准备

---

## 5. 数据层

### 5.1 市场广度计算

**RSP/SPY 相对表现**是最重要的广度指标：

```python
ratio_now  = rsp_price_today / spy_price_today
ratio_then = rsp_price_20d_ago / spy_price_20d_ago
breadth_trend = (ratio_now / ratio_then - 1) * 100
```

- `breadth_trend > 0`：等权重跑赢 → 广度扩张，健康牛市
- `breadth_trend < 0`：等权重跑输 → 广度收缩，仅少数龙头驱动，潜在风险

### 5.2 回撤计算

```python
52周最高价 = max(过去252个交易日收盘价)
当前回撤 % = (当前价格 / 52周最高价 - 1) * 100
```

这比"当日涨跌幅"更能反映当前所处的位置。

### 5.3 VIX 趋势

除了 VIX 的绝对值，趋势方向同样关键：

```
VIX = 32，且 5日前为 38 → 恐慌正在消退 → 可以开始建仓
VIX = 32，且 5日前为 22 → 恐慌仍在升温 → 等待稳定
```

### 5.4 CNN 恐惧与贪婪指数 API

```python
url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
# 无需 API key，直接 GET 请求
# 返回：当前值、昨收、1周前、1月前、1年前
```

该 API 非官方接口，若失效可降级处理（分类器对 `None` 值有容错逻辑）。

---

## 6. Agent 工作流程

### 6.1 消息循环架构

```
初始化消息列表：[系统提示, 用户消息（含投资组合）]
      │
      ▼
┌─────────────────────────────┐
│  调用 GPT-4o                │
│  messages + tools           │
└──────────────┬──────────────┘
               │
       ┌───────┴───────┐
       │ 有 tool_calls │ 无 tool_calls
       ▼               ▼
  执行工具           返回文本
  追加结果           （结束）
  到 messages
       │
       └──────► 循环（最多 12 次）
```

### 6.2 LLM 的典型工具调用顺序

一次完整 `analyze` 运行中，LLM 通常会按此顺序调用工具：

```
第1步：get_full_market_snapshot()          # 拉取全部市场数据（一次性）
第2步：classify_market_regime(snapshot)   # 确定场景
第3步：regime_to_ticker_suggestions(...)  # 获取推荐标的池
第4步：get_ticker_quote("NVDA")           # 按需查询特定仓位
        get_ticker_quote("TSLA")          # （可并行）
        ...
第5步：（无更多工具调用）生成最终中文分析报告
```

### 6.3 系统提示的关键约束

系统提示中几条硬性规则确保 LLM 行为可预测：

1. **先数据再观点**：防止 LLM 基于训练数据"记忆"来判断市场
2. **不质疑分类器**：场景由规则决定，LLM 只解释
3. **强制中文输出**：所有回复使用中文
4. **强制引用数值**：防止模糊表述
5. **强制说明置信度**：让用户知道结论有多可靠

---

## 7. 投资组合分析器

### 7.1 仓位类型处理

```
可定价仓位（stock / etf + 有 shares + buy_price）
   → 调用 yfinance 获取当前价格
   → 计算：市场价值 = shares × 当前价格
   → 计算：未实现盈亏 = 市场价值 - (shares × 成本价)
   → 计算：盈亏 % = (当前价 / 成本价 - 1) × 100

不可定价仓位（fund，仅有 value_sek）
   → 直接使用 value_sek 作为当前价值
   → 不计算盈亏（以 Avanza 导出值为准）
```

### 7.2 仓位权重计算

```python
total_value = sum(所有仓位市场价值) + cash
position_weight = position_value / total_value * 100
```

**注意**：MVP 阶段不做完整货币换算（SEK/USD/EUR 混合），直接将各货币面值相加。这对于大致了解集中度是够用的，后续可加入 FX 换算。

### 7.3 风险标志触发条件

```python
# 1. 现金不足
if cash / total_value < 0.05:
    flags.append("现金储备 < 5%，场景 2/3 买入时缺乏弹药")

# 2. 单一仓位过重
if position_weight > 25:
    flags.append(f"{ticker} 仓位 {weight:.1f}% > 25%")

# 3. 科技行业集中（简单规则）
tech_tickers = {"MSFT", "NVDA", "META", "AAPL", "TSLA", ...}
if tech_total_weight > 40:
    flags.append(f"科技相关敞口约 {tech_total_weight:.1f}% > 40%")

# 4. 防御板块单一主题
if saab + mildef > 15:
    flags.append("瑞典国防主题集中，单一板块风险")
```

---

## 8. 信号解读指南

### 8.1 VIX 快速参考

| VIX 水平 | 市场含义 |
|---|---|
| < 15 | 自满，历史上潜藏顶部风险 |
| 15–18 | 正常低波动 |
| 18–25 | 波动升温，开始留意 |
| 25–30 | 恐慌升温，场景 2 区间 |
| 30–40 | 高度恐慌 |
| > 40 | 极端恐慌（2008、2020 级别） |

### 8.2 恐惧与贪婪指数快速参考

| 值 | 含义 | 操作倾向 |
|---|---|---|
| 0–15 | 极度恐惧 | 场景 3 买入区（前提：信用正常） |
| 16–25 | 恐惧 | 场景 2 分批买入 |
| 26–45 | 偏恐惧 | 场景 1 正常定投 |
| 46–55 | 中性 | 场景 0 观望 |
| 56–75 | 贪婪 | 保持计划，注意广度 |
| 76–100 | 极度贪婪 | 场景 5 减仓警惕 |

### 8.3 信用市场健康度（场景 3 vs 4 的关键）

```
HYG 5日跌幅     DXY 20日涨幅    银行股跌幅     判断
──────────────────────────────────────────────────
> -3%          < 3%           > -8%          信用正常 → 市场恐慌是机会
≤ -3%          < 3%           > -8%          轻度信用压力 → 谨慎
≤ -3%          ≥ 3%           ≤ -8%          系统性风险 → 先防守
```

### 8.4 市场广度（RSP/SPY）

```
RSP 跑赢 SPY → 等权重领涨 → 广度扩张 → 健康
RSP 跑输 SPY → 仅少数巨头 → 广度收窄 → 脆弱
```

近年案例：
- **2023–2024**：SPY 涨幅 >> RSP（Magnificent 7 驱动），广度持续收窄
- **2003–2007**：RSP > SPY，广泛参与，健康牛市

---

## 9. 已知局限与后续改进

### MVP 阶段的已知局限

| 局限 | 影响 | 改进方向 |
|---|---|---|
| 无货币换算 | SEK/USD 混合计算仓位权重不精确 | 接入 FX API（ECB 免费提供） |
| MOVE 指数可能不可用 | 场景 4 少一个信号 | 接入 FRED API（免费）获取 MOVE 历史数据 |
| Avanza 基金无实时价格 | 基金价值依赖手动更新 | 接入 Avanza 的非官方 API |
| CNN F&G 为非官方接口 | 可能随时失效 | 加入备用来源（alternative.me） |
| 无历史回测 | 不知道分类器历史准确率 | 加入历史场景回测模块 |
| 每次运行独立 | 无法追踪建议与实际结果 | 加入 SQLite 日志 |
| 无定时运行 | 需手动执行 | 加入 cron / 调度任务 |

### 建议的迭代路径

```
当前（MVP）
   │
   ├── 阶段 2：FX 换算 + FRED API 信用利差（可选） + 历史回测
   │
   ├── 阶段 3：Streamlit 网页界面 + 每日定时推送
   │
   └── 阶段 4：多 Agent（主分析 + 怀疑论者）+ 完整回测框架
```

---

## 附录：关键阈值一览（`config.py`）

```python
THRESHOLDS = {
    # 场景 1：正常回调
    "s1_vix_low": 18.0,        # VIX 下界
    "s1_vix_high": 25.0,       # VIX 上界
    "s1_fg_low": 25,           # 恐惧与贪婪 下界
    "s1_fg_high": 45,          # 恐惧与贪婪 上界
    "s1_pullback_min": -5.0,   # SPY 最大回调
    "s1_pullback_max": -3.0,   # SPY 最小回调

    # 场景 2：恐慌回调
    "s2_vix_low": 25.0,        # VIX 下界
    "s2_vix_high": 35.0,       # VIX 上界
    "s2_fg_max": 25,           # F&G 最大值
    "s2_pullback_max": -7.0,   # SPY 至少回调 -7%

    # 场景 3：极端恐慌
    "s3_vix_min": 35.0,        # VIX 最低值
    "s3_fg_max": 15,           # F&G 最大值

    # 场景 4：系统性风险（任意 2 条触发 + VIX > 25）
    "s4_hyg_5d_drop": -3.0,    # HYG 5日跌幅
    "s4_dxy_20d_surge": 3.0,   # DXY 20日涨幅
    "s4_bank_5d_drop": -8.0,   # 银行 ETF 5日跌幅
    "s4_move_high": 140.0,     # MOVE 指数上界
    "s4_vix_floor": 25.0,      # 系统性风险 VIX 最低要求

    # 场景 5：过度贪婪
    "s5_vix_max": 15.0,        # VIX 最大值（自满区）
    "s5_fg_min": 75,           # F&G 最小值（极度贪婪）
}
```

所有阈值均在 `config.py` 中集中管理，可根据个人风险偏好自由调整，**无需改动任何业务逻辑代码**。

---

*本文档随项目持续更新。如有疑问或改进建议，直接修改本文件。*
