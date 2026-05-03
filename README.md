<p align="center">
  <img src="./frontend/src/assets/logo.svg" width="132" alt="OKX Trader Logo" />
</p>

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=700&size=34&duration=2600&pause=900&color=126CFF&center=true&vCenter=true&width=760&height=70&lines=OKX+TRADER;AI-Driven+Perpetual+Trading+Engine;Risk+First+%C2%B7+Execute+with+Discipline" alt="OKX Trader animated title" />
</p>

<p align="center">
  面向 OKX 永续合约的自动交易系统 · FastAPI 后端 · Vue 3 管理面板 · 技术/AI/混合决策
</p>

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=500&size=15&duration=3200&pause=600&color=0B1118&center=true&vCenter=true&width=860&height=32&lines=Market+Data+%E2%86%92+Signal+Engine+%E2%86%92+Risk+Check+%E2%86%92+Execution+%E2%86%92+Managed+Exit;%E8%A1%8C%E6%83%85%E6%95%B0%E6%8D%AE+%E2%86%92+%E7%AD%96%E7%95%A5%E4%BF%A1%E5%8F%B7+%E2%86%92+%E9%A3%8E%E6%8E%A7%E6%A3%80%E6%9F%A5+%E2%86%92+%E8%AE%A2%E5%8D%95%E6%89%A7%E8%A1%8C+%E2%86%92+%E6%8C%81%E4%BB%93%E7%9B%91%E6%8E%A7" alt="Trading flow animated subtitle" />
</p>

<p align="center">
  <a href="#-项目简介"><img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" /></a>
  <a href="#-技术栈"><img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white" /></a>
  <a href="#-技术栈"><img src="https://img.shields.io/badge/Vue-3.5-4FC08D?style=for-the-badge&logo=vuedotjs&logoColor=white" /></a>
  <a href="#-技术栈"><img src="https://img.shields.io/badge/TypeScript-6-3178C6?style=for-the-badge&logo=typescript&logoColor=white" /></a>
  <a href="#-快速开始"><img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/OKX-Exchange-121212?style=flat-square&logo=okx&logoColor=white" />
  <img src="https://img.shields.io/badge/Market-Perpetual_Swap-00D4AA?style=flat-square" />
  <img src="https://img.shields.io/badge/AI-OpenAI_Compatible-412991?style=flat-square&logo=openai&logoColor=white" />
  <img src="https://img.shields.io/badge/DB-SQLite_WAL-003B57?style=flat-square&logo=sqlite&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" />
</p>

> [!WARNING]
> 本项目会连接交易所并可能执行真实订单。请先使用 `OKX_DEMO=true` 的模拟盘充分验证；切换到实盘前，请确认 API 权限、策略启停状态、网络暴露范围和风控参数。交易有风险，盈亏自负。


---

## 项目简介

**OKX Trader** 是一套面向 OKX 永续合约的**自动量化交易系统**。它内置 **11 个已注册的 strategy_type**，支持**纯技术指标 / AI 驱动 / 混合决策**三种模式，配备 Web 管理面板、实时 WebSocket 推送、SQLite 持久化、基础风控能力和永续合约智能分析报告。

核心链路：行情数据 → 技术指标 / AI 分析 → 策略信号 → 风控检查 → 订单执行 → 持仓监控 → 前端实时展示。

<table align="center">
  <tr>
    <td align="center"><b>Strategy Runner</b><br/><sub>异步策略调度<br/>多交易对扫描</sub></td>
    <td align="center"><b>Risk Manager</b><br/><sub>日亏损限制<br/>连败冷却</sub></td>
    <td align="center"><b>OKX Execution</b><br/><sub>杠杆设置<br/>市价下单 / 平仓</sub></td>
    <td align="center"><b>Realtime Dashboard</b><br/><sub>WebSocket 推送<br/>账户 / 持仓 / 日志</sub></td>
  </tr>
</table>

<table align="center">
  <tr>
    <td align="center"><b>🔧 技术指标</b><br/><sub>SMMA · EMA · RSI · ATR<br/>ADX · MACD · BOLL</sub></td>
    <td align="center"><b>🧠 AI 大脑</b><br/><sub>OpenAI 兼容 API<br/>Hybrid 确认模式</sub></td>
    <td align="center"><b>🛡️ 风控引擎</b><br/><sub>日亏损上限 · 连败冷却<br/>仓位互斥 · OCO 保护</sub></td>
    <td align="center"><b>📊 管理退出</b><br/><sub>TP1/TP2 · 保本止损<br/>极限止盈 · 时间止损</sub></td>
  </tr>
</table>

---

## 🧰 技术栈

| 层级 | 技术 |
|:---|:---|
| 后端 | Python 3.11+ · FastAPI · Uvicorn · Pydantic v2 · Loguru |
| 交易所 | python-okx · OKX REST API · 模拟盘/实盘 flag 切换 |
| 数据 | SQLite · aiosqlite · WAL 模式 |
| 策略/指标 | pandas · NumPy · 自定义技术指标与策略注册表 |
| AI | OpenAI 兼容 API · `technical` / `ai` / `hybrid` 决策模式 |
| 前端 | Vue 3 · TypeScript · Vite · Pinia · Vue Router · Element Plus · ECharts |
| 部署 | Docker 多阶段构建 · docker compose 单服务部署 |

---

## 🏗️ 系统架构

```
                               ┌──────────────────────────┐
                               │      Vue3 Web 面板        │
                               │   Element Plus 亮色主题    │
                               │   Pinia 状态 · ECharts    │
                               └────────────┬─────────────┘
                                            │ WebSocket ↗️
                               ┌────────────┴─────────────┐
                               │       FastAPI 后端        │
                               │                           │
           ┌───────────────────┤   StrategyRunner 引擎     ├───────────────────┐
           │                   │   TradeExecutor  执行器   │                   │
           │                   │   RiskManager    风控     │                   │
           │                   │   PositionMonitor 监控    │                   │
           │                   └──┬────────┬──────────┬───┘                   │
           │                      │        │          │                       │
     ┌─────▼──────┐      ┌───────▼──┐ ┌───▼────┐ ┌───▼──────────┐    ┌───────▼──────┐
     │ 技术指标    │      │ AI 决策   │ │ 交易所  │ │  数据持久层   │    │  通知通道     │
     │ indicators │      │ analyzer │ │ OKX    │ │  SQLite WAL  │    │  Telegram    │
     │ NumPy 计算  │      │ OpenAI   │ │ Client │ │  aiosqlite   │    │  Bot         │
     └────────────┘      └──────────┘ └────────┘ └──────────────┘    └──────────────┘
```

---

## 🔥 交易策略

<table>
  <tr>
    <th>策略</th>
    <th>方向</th>
    <th>决策</th>
    <th>核心逻辑</th>
  </tr>
  <tr>
    <td><b>SMMA 压制做空</b></td>
    <td>🔴 空</td>
    <td>技术</td>
    <td>SMMA 趋势 + 量能异动 + 看跌 K 线形态</td>
  </tr>
  <tr>
    <td><b>SMMA 支撑做多</b></td>
    <td>🟢 多</td>
    <td>技术</td>
    <td>SMMA 多头镜像 — 均线支撑 + 放量拉升确认</td>
  </tr>
  <tr>
    <td><b>脉冲急拉做空</b></td>
    <td>🔴 空</td>
    <td>技术</td>
    <td>动态涨幅扫描 + EMA/BOLL 偏离 + 量价背离 + 长上影</td>
  </tr>
  <tr>
    <td><b>均值回归做空</b></td>
    <td>🔴 空</td>
    <td>技术</td>
    <td>极端偏离后的回归交易，管理退出 (TP1/TP2/保本)</td>
  </tr>
  <tr>
    <td><b>趋势回踩二次启动</b></td>
    <td>🟢 多</td>
    <td>技术</td>
    <td>1H 趋势确认 + 15m BOLL 中线回踩 + 量能验证</td>
  </tr>
  <tr>
    <td><b>BOLL 中线收复</b></td>
    <td>🟢 多</td>
    <td>技术</td>
    <td>长时间压制后价格收复 BOLL 中线 — 空头衰竭信号</td>
  </tr>
  <tr>
    <td><b>高潮衰竭剥头皮</b></td>
    <td>🔴 空</td>
    <td>技术</td>
    <td>冲顶放量后剥头皮 — 量能高潮 + 价格衰竭</td>
  </tr>
  <tr>
    <td><b>AI 激进短线 5m</b></td>
    <td>🟡 双向</td>
    <td>混合</td>
    <td>EMA 方向锁定 + AI 确认，快节奏趋势跟随</td>
  </tr>
  <tr>
    <td><b>AI 中短线趋势 15m</b></td>
    <td>🟡 双向</td>
    <td>混合</td>
    <td>ADX 强度 + OI 共振 + 趋势回踩 + AI 确认</td>
  </tr>
  <tr>
    <td><b>AI 稳健趋势 1h</b></td>
    <td>🟡 双向</td>
    <td>混合</td>
    <td>4 项硬性技术条件预筛 + AI 最终确认，保守稳健</td>
  </tr>
  <tr>
    <td><b>AI EMA 交叉预判 15m</b></td>
    <td>🟡 双向</td>
    <td>混合</td>
    <td>EMA 7/120 金叉死叉预判，提前捕捉趋势转换</td>
  </tr>
</table>

> 当前注册策略共 **11 个 strategy_type**。三种决策模式：`technical` 纯技术指标 · `ai` 纯 AI 驱动 · `hybrid` 技术预筛 + AI 确认。

---

## ⚡ 快速开始

### 前置要求

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python" />
  <img src="https://img.shields.io/badge/Node.js-20+-green?logo=nodedotjs" />
  <img src="https://img.shields.io/badge/pnpm-latest-orange?logo=pnpm" />
</p>

### 方式一：Docker 一键部署

```bash
# 1. 配置
cp backend/.env.example .env
vim .env   # 填入 OKX API 密钥

# 2. 启动
docker compose up -d

# 3. 访问
# 浏览器打开 http://localhost:8000
```

### 方式二：本地开发

```bash
# === 后端 ===
cd backend
cp .env.example .env      # 编辑填入密钥
pip install -r requirements.txt
python main.py             # → http://localhost:8000

# === 前端 (新终端) ===
cd frontend
pnpm install
pnpm dev                   # → http://localhost:5173
```

### 环境变量

| 变量 | 说明 | 必填 |
|:---|:---|:---:|
| `OKX_API_KEY` | OKX API 密钥 | ✅ |
| `OKX_SECRET_KEY` | OKX Secret 密钥 | ✅ |
| `OKX_PASSPHRASE` | OKX Passphrase | ✅ |
| `OKX_DEMO` | 模拟盘模式 (`true`/`false`) | ✅ |
| `OPENAI_API_KEY` | AI 模式 API 密钥 | 可选 |
| `OPENAI_API_URL` | OpenAI 兼容 API 地址，默认 `https://api.openai.com/v1` | 可选 |
| `OPENAI_MODEL` | AI 模型名，默认 `gpt-4o-mini` | 可选 |
| `HTTP_PROXY` / `HTTPS_PROXY` | 代理地址 | 可选 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 可选 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可选 |
| `PORT` | 后端端口 (默认 8000) | 可选 |
| `ADMIN_PASSWORD` | 面板登录密码；留空或不设置则不启用登录 | 可选 |

> Docker 部署读取根目录 `.env`；本地后端开发通常读取 `backend/.env`。修改 OKX 凭证、模拟盘/实盘模式、AI 配置或 `ADMIN_PASSWORD` 后，建议重启后端以确保已初始化的客户端实例同步更新。

> API 文档：启动后端后打开 `http://localhost:8000/docs` 查看完整 Swagger UI

---

## 🛡️ 风控体系

```
策略级            ──  日亏损上限 ── 连败冷却 (3连败=停1H) ── 最大并发仓位
                   ──  单币种日交易上限 ── 仓位币种互斥
订单级            ──  OCO 自动保护 ── Market Order 即刻成交
管理退出          ──  TP1 减仓50% ── TP2 全平 ── 保本止损
                   ──  极限止盈(2%/30s) ── 时间止损
```

---

## 📊 Web 管理面板

| 页面 | 功能 |
|:---|:---|
| **Dashboard** | 账户总览 · 策略网格 · 实时 PnL · 一键启停 · 模式切换 |
| **Strategy Detail** | PnL 曲线 (ECharts) · 信号历史 · 持仓追踪 · 胜率统计 |
| **Perpetual Analysis** | 交易对选择 · OKX 实时数据拉取 · 综合评分 · 规则触发明细 · 多周期/支撑压力/资金费率/OI/成交量/情绪/订单簿/机构行为/市场阶段/策略匹配/风险收益比/多角色/冲突/交易计划分析 · AI 完整报告 |
| **Analysis History** | 自动保存完整分析快照 · 交易对/时间筛选 · 历史报告详情 · 当前实时价对比 · 同币种评分变化 · K 线复盘关键价位 · 备注 |
| **Settings** | OKX API 配置 · AI API 配置 · Telegram 通知 · 连通性测试 |
| **Log Viewer** | 实时日志推流 · 分类过滤 (信号 / 交易 / 错误) |

永续合约智能分析入口在顶部导航的分析按钮，接口为 `POST /api/perpetual-analysis`，请求体：

```json
{
  "symbol": "BTC-USDT-SWAP"
}
```

该功能只生成市场状态诊断、风险参考和交易计划草稿，不会触发下单。结构化报告不依赖 AI Key；若配置了 `OPENAI_API_KEY`，后端会额外生成完整自然语言分析报告。每次分析完成后会写入 SQLite 表 `perpetual_analysis_history`，保存完整 JSON 快照（评分、指标、关键价位、AI 报告、交易计划等），并在前端历史页支持筛选、详情查看、评分变化对比、复盘和备注。历史详情复用实时分析报告界面，并额外展示当前实时价对比。前端对该分析接口单独使用 1 小时请求超时，其他面板 API 仍保持 15 秒默认超时。

历史分析相关接口：

| 方法 | 路径 | 用途 |
|:---|:---|:---|
| `GET` | `/api/perpetual-analysis/history` | 历史列表，支持 `symbol`、`start`、`end`、`limit`、`offset` |
| `GET` | `/api/perpetual-analysis/history/{id}` | 完整历史快照，并附带当前实时价对比 |
| `PATCH` | `/api/perpetual-analysis/history/{id}` | 更新 `note` |
| `DELETE` | `/api/perpetual-analysis/history/{id}` | 删除指定历史分析记录 |
| `GET` | `/api/perpetual-analysis/history/score-series` | 同一交易对多次分析评分变化 |
| `GET` | `/api/perpetual-analysis/history/{id}/replay` | 拉取分析时间点后的 K 线，检查关键价位是否触达 |

---

## 🗂️ 项目结构

```
okx-trader/
├── backend/
│   ├── main.py              # FastAPI 入口 + 生命周期管理
│   ├── config.py            # 环境变量配置中心
│   ├── api/                 # REST API 路由层
│   │   ├── account.py       #   账户 / 余额
│   │   ├── positions.py     #   持仓查询
│   │   ├── strategies.py    #   策略管理
│   │   ├── market.py        #   行情数据
│   │   ├── perpetual_analysis.py # 永续合约智能分析
│   │   └── settings.py      #   系统配置
│   ├── analysis/
│   │   ├── perpetual.py     # 永续合约结构化评分与规则引擎
│   │   └── history.py       # 分析历史持久化、评分序列与复盘计算
│   ├── core/                # 核心引擎
│   │   ├── strategy_runner.py   # 策略编排器 (异步轮询)
│   │   ├── trade_executor.py    # 订单执行 + OCO 挂载
│   │   ├── risk_manager.py      # 风控决策 (日重置)
│   │   └── position_monitor.py  # 管理退出状态机
│   ├── strategies/          # 策略实现层
│   │   ├── base.py          #   IStrategy 抽象接口
│   │   ├── registry.py      #   策略注册表
│   │   ├── smma_short.py    #   SMMA 做空
│   │   ├── smma_long.py     #   SMMA 做多
│   │   ├── spike_fade_mr.py #   脉冲 + 均值回归
│   │   ├── boll_trend_pullback.py    # 趋势回踩
│   │   ├── boll_midline_reclaim.py   # 中线收复
│   │   ├── climax_exhaustion_scalp.py # 高潮衰竭
│   │   └── ai_strategy.py   #   AI 策略 (4 个实例)
│   ├── exchange/
│   │   └── okx_client.py    # OKX SDK 封装
│   ├── indicators/
│   │   └── technical.py     # NumPy 技术指标 (纯计算)
│   ├── ai/
│   │   └── analyzer.py      # OpenAI 兼容 LLM 客户端
│   ├── db/
│   │   └── database.py      # SQLite + Schema + 种子数据
│   ├── ws/
│   │   └── __init__.py      # WebSocket 广播管理器
│   ├── utils/
│   │   └── logger.py        # Loguru 日志 (日轮转, 30日留存)
│   └── models/              # Pydantic 数据模型
├── frontend/
│   └── src/
│       ├── views/           # Dashboard · Detail · Settings
│       ├── components/      # StrategyCard · PnlChart · LogViewer
│       ├── stores/trading.ts    # Pinia Store (WS 实时更新)
│       ├── api/index.ts     # Axios API 客户端
│       ├── assets/logo.svg  # 项目 Logo
│       ├── router/          # Vue Router
│       └── styles/index.css # 自定义主题系统
├── Dockerfile               # 多阶段构建 (Node + Python)
├── docker-compose.yml       # 单服务部署
└── backend/.env.example     # 环境变量示例
```

---

## 🧠 AI 决策引擎

```
K线数据 ──→ 技术指标计算 ──→ 结构化 Prompt ──→ LLM 推理
                                                  │
                                    ┌─────────────┴─────────────┐
                                    │                           │
                              Hybrid 模式                  Pure AI 模式
                          技术预筛 + AI 确认               纯 AI 判断
                                    │                           │
                                    └─────────────┬─────────────┘
                                                  │
                                            ┌─────▼─────┐
                                            │ 信号输出   │
                                            │ 方向+置信度 │
                                            │ +推理过程   │
                                            └───────────┘
```

AI 决策支持任意 OpenAI 兼容 API（OpenAI / DeepSeek / 本地模型），通过 `OPENAI_API_URL` 配置。

---

## 📈 技术指标清单

| 指标 | 缩写 | 用途 |
|:---|:---|:---|
| 平滑移动平均 | SMMA | 趋势判断核心 |
| 指数移动平均 | EMA | 快慢均线交叉信号 |
| 简单移动平均 | SMA | 基准均线参照 |
| 相对强弱指数 | RSI | 超买超卖判断 |
| 平均真实波幅 | ATR | 波动率 + 止损计算 |
| 平均趋向指数 | ADX | 趋势强度评估 |
| 移动平均趋同 | MACD | 动量背离检测 |
| 布林带 | BOLL | 波动率通道 + 偏离信号 |
| K线聚合 | — | 任意周期 K 线合成 |

> 所有指标均为 **纯 NumPy 向量化计算**，无循环，毫秒级响应。

---

## 🤝 贡献

欢迎 Issue / PR。请确保代码风格与现有项目一致。

---

## 🔒 安全与实盘检查

- 默认使用 `OKX_DEMO=true` 模拟盘；切换 `OKX_DEMO=false` 前确认策略是否会随服务启动自动运行。
- 不要提交 `.env`、API Key、Passphrase 或真实账户信息。
- 如果部署到公网，请先补充访问鉴权，并限制 CORS 来源。
- `Settings` 相关接口会读写配置，生产环境不要在无鉴权场景下暴露。
- 定期核对 OKX 实际持仓与本地 `positions` / `trades` 记录，避免下单成功但本地记录失败造成状态不一致。

---

## 📜 许可

MIT License · 交易有风险，请自行评估

---

<p align="center">
  <sub>Built with Python · FastAPI · Vue 3 · OKX Open API</sub>
</p>
