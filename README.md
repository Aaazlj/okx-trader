# OKX 自动交易系统

基于 Python (FastAPI) + Vue3 (Vite + Element Plus) 的 OKX 永续合约自动交易系统。

## 功能特性

- 🔄 **4 种交易策略**：SMMA 做空、SMMA 做多、脉冲急拉做空、均值回归
- ⚙️ **策略启停控制**：每个策略可独立启动/暂停
- 📊 **多交易对支持**：每个策略可配置多个交易对
- 🤖 **双决策模式**：纯技术指标 或 AI 驱动（OpenAI 兼容 API）
- 📱 **Web 管理面板**：暗色主题，实时状态推送
- 🐳 **Docker 一键部署**

## 快速开始

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 .env 填入 OKX API 密钥
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt
python main.py
```

### 3. 启动前端（开发模式）

```bash
cd frontend
pnpm install
pnpm dev
```

访问 http://localhost:5173

### 4. Docker 部署

```bash
cp backend/.env.example .env
# 编辑 .env 填入配置

docker compose up -d
```

访问 http://localhost:8000

## 项目结构

```
okx-trader/
├── backend/           # Python 后端
│   ├── main.py        # FastAPI 入口
│   ├── config.py      # 配置管理
│   ├── api/           # REST API
│   ├── core/          # 策略引擎
│   ├── strategies/    # 策略实现
│   ├── exchange/      # OKX 客户端
│   ├── indicators/    # 技术指标
│   ├── ai/            # AI 决策
│   ├── db/            # SQLite
│   └── ws/            # WebSocket
├── frontend/          # Vue3 前端
│   └── src/
│       ├── views/     # 页面
│       ├── components/# 组件
│       ├── stores/    # Pinia 状态
│       └── api/       # API 调用
├── Dockerfile
├── docker-compose.yml
└── .env
```

## API 文档

启动后访问 http://localhost:8000/docs 查看 Swagger 文档。
