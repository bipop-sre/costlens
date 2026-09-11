# CostLens AI Agent 🚀

AI 驱动的多云成本监控与优化智能体，帮助企业实时监测公有云支出、发现异常、优化资源。

## 核心能力

- **多云成本聚合** — 统一查看阿里云 / 腾讯云的成本数据
- **智能异常检测** — 基于统计模型自动发现成本突增、异常偏离
- **成本趋势分析** — 日趋势、移动平均、环比同比、成本预测
- **AI 优化建议** — 预留实例、闲置资源清理、存储分层、架构优化
- **预算管理** — 预算执行监控、超支预警、预测分析
- **自然语言交互** — 通过对话方式查询和分析成本数据

## 架构

```
┌──────────────────────────────────────────────────┐
│                  CostLens                      │
├──────────────┬───────────────┬────────────────────┤
│  LLM Agent   │  Analysis     │  Cloud Connectors  │
│  (OpenAI)    │  Engine       │  ├── Alibaba BSS   │
│  - Tool Call │  - Trend      │  └── Tencent Billing│
│  - Streaming │  - Anomaly    │                    │
│  - Chat      │  - Budget     │                    │
│              │  - Optimizer  │                    │
├──────────────┴───────────────┴────────────────────┤
│              FastAPI REST API                      │
│     /api/chat  /api/cost  /health  /metrics       │
└──────────────────────────────────────────────────┘
```

## 快速开始

### 安装

```bash
cd costlens
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 填入云厂商凭证和 OpenAI API Key
```

关键配置项：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `OPENAI_MODEL` | LLM 模型，默认 `gpt-4o` |
| `OPENAI_BASE_URL` | API 端点，支持兼容 OpenAI 的第三方服务 |
| `ENABLED_PROVIDERS` | 启用的云厂商，逗号分隔：`alibaba,tencent` |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | 阿里云 AccessKey ID |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 阿里云 AccessKey Secret |
| `ALIBABA_CLOUD_REGION` | 阿里云地域，默认 `cn-hangzhou` |
| `TENCENT_CLOUD_SECRET_ID` | 腾讯云 SecretId |
| `TENCENT_CLOUD_SECRET_KEY` | 腾讯云 SecretKey |
| `TENCENT_CLOUD_REGION` | 腾讯云地域，默认 `ap-guangzhou` |

### 运行

**Web + Bot 统一启动（推荐）：**
```bash
python run_web.py
```

启动后 Web Dashboard 在 `http://localhost:8080`，企业微信 Bot 自动连接（需配置 `WECHAT_WORK_BOT_ID` 和 `WECHAT_WORK_BOT_SECRET`）。

**仅 Bot 模式：**
```bash
python run_bot.py
```

**交互对话模式：**
```bash
costlens chat
```

**API 服务模式：**
```bash
costlens server --port 8000
```

**一次性分析：**
```bash
costlens analyze --days 30
```

## API 接口

### 对话接口
```bash
# 发送消息
POST /api/chat
{
  "message": "这个月阿里云花了多少钱？",
  "session_id": "optional-session-id",
  "stream": false
}

# SSE 流式响应
POST /api/chat
{
  "message": "最近有什么成本异常？",
  "stream": true
}
```

### 成本数据
```bash
GET /api/cost/summary?days=30&provider=alibaba
GET /api/cost/analysis?days=30
GET /api/cost/anomalies?days=30
GET /api/cost/recommendations?days=30
GET /api/cost/trends?days=30
```

### 预算管理
```bash
POST /api/budgets
{
  "name": "月度阿里云预算",
  "amount": 50000,
  "currency": "CNY",
  "provider": "alibaba"
}
```

### 健康检查
```bash
GET /health
```

### Prometheus 指标
```bash
GET /metrics
```

## 对话示例

```
You> 这个月阿里云成本是多少？

Agent> 根据阿里云 BSS 数据，本月（2026-09-01 至 2026-09-11）
阿里云总成本为 ¥38,200.00。

前5大服务：
1. 云服务器 ECS — ¥15,800 (41.4%)
2. 云数据库 RDS — ¥8,500 (22.3%)
3. 对象存储 OSS — ¥5,200 (13.6%)
4. 负载均衡 SLB — ¥3,600 (9.4%)
5. 容器服务 ACK — ¥2,800 (7.3%)

环比上月增长 5.2%，主要增长来自 ECS 实例扩容。

You> 有什么优化建议？

Agent> 发现 5 条优化建议，预计月省 ¥12,000：

🔴 高优先级：
- ECS 预留实例：当前月成本 ¥15,800，购买 1 年期 RI 可节省约 35%（¥5,530/月）
- RDS 预留实例：月成本 ¥8,500，可节省约 30%（¥2,550/月）

🟡 中优先级：
- 闲置云盘：发现 3 个未挂载的云盘，释放可省 ¥450/月
- ACK 节点右尺寸：2 个节点 CPU 利用率低于 10%

🟢 低优先级：
- OSS 存储分层：建议将 90 天未访问的数据转为低频存储
```

## 项目结构

```
costlens/
├── costlens/
│   ├── agent/              # AI Agent 核心
│   │   ├── core.py         # LLM 编排 & 工具调用
│   │   ├── chat.py         # 会话管理
│   │   └── tools/          # Agent 可用工具
│   │       └── registry.py # 工具注册表
│   ├── cloud/              # 多云连接器
│   │   ├── base.py         # 抽象接口 & 工厂
│   │   ├── alibaba.py      # 阿里云 BSS
│   │   └── tencent.py      # 腾讯云 Billing
│   ├── web/                # Web Dashboard
│   │   ├── app.py          # FastAPI 应用 (含 /health, /metrics)
│   │   ├── auth.py         # Token 认证
│   │   └── templates/      # 前端模板
│   ├── analysis/           # 分析引擎
│   │   ├── analyzer.py     # 主编排器
│   │   ├── trend.py        # 趋势分析
│   │   ├── anomaly.py      # 异常检测
│   │   ├── budget_analyzer.py  # 预算分析
│   │   └── optimizer.py    # 优化建议
│   ├── models/             # 数据模型
│   │   ├── cost.py         # 成本数据
│   │   ├── budget.py       # 预算
│   │   ├── recommendation.py # 优化建议
│   │   └── alert.py        # 告警
│   ├── wechat_bot.py       # 企业微信智能 Bot
│   ├── notifications.py    # 通知推送
│   ├── scheduler.py        # 定时任务
│   ├── config.py           # 配置管理
│   └── main.py             # 入口点
├── run_web.py              # Web + Bot 统一启动入口
├── run_bot.py              # 独立 Bot 启动入口
├── tests/                  # 测试
├── Dockerfile              # 容器构建
├── docker-compose.yml      # 本地编排
└── pyproject.toml          # 项目配置
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 代码检查
ruff check costlens/
ruff format costlens/
```

## 技术栈

- **Python 3.14+** — 核心语言
- **FastAPI** — REST API 框架
- **OpenAI API** — LLM 推理和工具调用
- **NumPy** — 数值分析和趋势预测
- **alibabacloud-bssopenapi** — 阿里云 SDK
- **tencentcloud-sdk-python** — 腾讯云 SDK
- **wecom-aibot-sdk** — 企业微信智能 Bot SDK
- **Rich** — 终端 UI

## 部署

### Docker 构建

```bash
docker build -t costlens:latest .
```

### Kubernetes 部署

通过 Helm 模板部署，关键环境变量：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM API 密钥 |
| `OPENAI_BASE_URL` | LLM API 端点 |
| `OPENAI_MODEL` | LLM 模型名称 |
| `WECHAT_WORK_BOT_ID` | 企业微信 Bot ID |
| `WECHAT_WORK_BOT_SECRET` | 企业微信 Bot Secret |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | 阿里云 AccessKey |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 阿里云 Secret |
| `TENCENT_CLOUD_SECRET_ID` | 腾讯云 SecretId |
| `TENCENT_CLOUD_SECRET_KEY` | 腾讯云 SecretKey |
| `DB_TYPE` | 数据库类型：`sqlite` 或 `oceanbase` |
| `OCEANBASE_HOST` | OceanBase 地址 |
| `OCEANBASE_PORT` | OceanBase 端口 |
| `OCEANBASE_USER` | OceanBase 用户 |
| `OCEANBASE_PASSWORD` | OceanBase 密码 |
| `OCEANBASE_DATABASE` | OceanBase 数据库名 |

### 健康检查

```bash
# 存活探针
curl http://localhost:8080/health
# 返回: {"status": "healthy"} 或 {"status": "degraded"}

# Prometheus 指标
curl http://localhost:8080/metrics
```

## 扩展功能

CostLens 提供四个核心扩展功能：

### 📊 Prometheus 指标导出

提供 `/metrics` 端点，导出 Prometheus 格式的成本指标，可集成到 Grafana 进行可视化。

```bash
# 访问指标
curl http://localhost:8080/metrics
```

支持的指标：
- `costlens_up` — 服务是否在线
- `costlens_records_total` — 成本记录总数
- `costlens_records_by_provider` — 按云厂商分类的记录数
- `costlens_alerts_total` — 告警数量（按严重等级）
- `costlens_alerts_unacknowledged` — 未确认告警数
- `costlens_balance_available` — 各云厂商可用余额

### 🔔 告警推送（钉钉/飞书/企业微信）

支持将成本异常告警推送到钉钉、飞书、企业微信群机器人。

```bash
# 配置通知渠道
curl -X POST http://localhost:8080/api/storage/notifications/configure \
  -d '{
    "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
    "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
  }'

# 发送待处理告警
curl -X POST http://localhost:8080/api/storage/notifications/send-pending
```

### 💾 数据持久化

支持 SQLite 和 OceanBase 两种存储后端，存储成本数据、告警、优化建议和预算配置。

```bash
# 查询成本记录
curl "http://localhost:8080/api/storage/costs?days=30&provider=alibaba"

# 查询告警
curl "http://localhost:8080/api/storage/alerts?severity=critical"

# 查询优化建议
curl "http://localhost:8080/api/storage/recommendations?priority=high"

# 创建预算
curl -X POST http://localhost:8080/api/storage/budgets \
  -d '{"name": "月度阿里云", "amount": 50000, "provider": "alibaba"}'
```

### 🤖 企业微信智能 Bot

通过企业微信直接与 CostLens 对话，支持：
- 自然语言查询成本、余额、趋势
- AI 驱动的优化建议
- 定时账单推送（通过 Scheduler）

配置 `WECHAT_WORK_BOT_ID` 和 `WECHAT_WORK_BOT_SECRET` 后，启动 `run_web.py` 即可自动连接。

## 完整演示

```bash
# 1. 生成演示数据
costlens demo

# 2. 启动 Web 服务（含 Bot）
python run_web.py

# 3. 查看健康状态
curl http://localhost:8080/health

# 4. 查询成本数据
curl "http://localhost:8080/api/storage/costs?days=30"

# 5. 查看告警
curl http://localhost:8080/api/storage/alerts

# 6. 查看优化建议
curl http://localhost:8080/api/storage/recommendations

# 7. 访问 Prometheus 指标
curl http://localhost:8080/metrics

# 8. 使用 AI 对话
curl -X POST http://localhost:8080/api/chat \
  -d '{"message": "这个月成本是多少？有什么优化建议？"}'
```

## License

MIT
