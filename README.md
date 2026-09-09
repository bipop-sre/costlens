# CostLens AI Agent 🚀

AI 驱动的多云成本监控与优化智能体，帮助企业实时监测公有云支出、发现异常、优化资源。

## 核心能力

- **多云成本聚合** — 统一查看 AWS / Azure / GCP / 阿里云的成本数据
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
│  (OpenAI)    │  Engine       │  ┌─── AWS CE       │
│  - Tool Call │  - Trend      │  ├── Azure CM      │
│  - Streaming │  - Anomaly    │  ├── GCP BigQuery  │
│  - Chat      │  - Budget     │  └── Alibaba BSS   │
│              │  - Optimizer  │                    │
├──────────────┴───────────────┴────────────────────┤
│              FastAPI REST API                      │
│         /api/chat  /api/cost  /api/health         │
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
| `ENABLED_PROVIDERS` | 启用的云厂商，逗号分隔：`aws,azure,gcp,alibaba` |

### 运行

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
  "message": "这个月 AWS 花了多少钱？",
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
GET /api/cost/summary?days=30&provider=aws
GET /api/cost/analysis?days=30
GET /api/cost/anomalies?days=30
GET /api/cost/recommendations?days=30
GET /api/cost/trends?days=30
```

### 预算管理
```bash
POST /api/budgets
{
  "name": "Monthly AWS Budget",
  "amount": 10000,
  "currency": "USD",
  "provider": "aws"
}
```

### 健康检查
```bash
GET /api/health
```

## 对话示例

```
You> 这个月 AWS 成本是多少？

Agent> 根据 AWS Cost Explorer 数据，本月（2024-01-01 至 2024-01-31）
AWS 总成本为 $12,450.00。

前5大服务：
1. Amazon EC2 — $5,200 (41.8%)
2. Amazon RDS — $2,800 (22.5%)
3. Amazon S3 — $1,500 (12.0%)
4. Amazon ECS — $1,200 (9.6%)
5. AWS Lambda — $800 (6.4%)

环比上月增长 8.3%，主要增长来自 EC2。

You> 有什么优化建议？

Agent> 发现 5 条优化建议，预计月省 $4,200：

🔴 高优先级：
- EC2 预留实例：当前月成本 $5,200，购买 1 年期 RI 可节省约 35%（$1,820/月）
- RDS 预留实例：月成本 $2,800，可节省约 30%（$840/月）

🟡 中优先级：
- 闲置 EBS 卷：发现 3 个未挂载的卷，释放可省 $150/月
- ECS 任务右尺寸：2 个服务 CPU 利用率低于 10%

🟢 低优先级：
- S3 存储分层：建议将 90 天未访问的数据转为 Infrequent Access
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
│   │   ├── aws.py          # AWS Cost Explorer
│   │   ├── azure.py        # Azure Cost Management
│   │   ├── gcp.py          # GCP BigQuery Billing
│   │   └── alibaba.py      # 阿里云 BSS
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
│   ├── api/                # REST API
│   │   └── app.py          # FastAPI 应用
│   ├── config.py           # 配置管理
│   └── main.py             # 入口点
├── tests/                  # 测试
├── .env.example            # 配置模板
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

- **Python 3.11+** — 核心语言
- **FastAPI** — REST API 框架
- **OpenAI API** — LLM 推理和工具调用
- **NumPy** — 数值分析和趋势预测
- **boto3** — AWS SDK
- **azure-mgmt-costmanagement** — Azure SDK
- **google-cloud-billing** — GCP SDK
- **alibabacloud-bssopenapi** — 阿里云 SDK
- **Rich** — 终端 UI

## License

MIT

## 扩展功能

CostLens 提供四个核心扩展功能：

### 📊 Prometheus 指标导出

提供 `/metrics` 端点，导出 Prometheus 格式的成本指标，可集成到 Grafana 进行可视化。

```bash
# 访问指标
curl http://localhost:8000/metrics
```

支持的指标：
- `costlens_cloud_cost_total` — 各云厂商总成本
- `costlens_cloud_cost_daily_avg` — 日均成本
- `costlens_cloud_service_cost` — 按服务分类的成本（Top 10）
- `costlens_alerts_total` — 告警数量
- `costlens_recommendations_total` — 优化建议数量
- `costlens_potential_savings_total` — 预计可节省金额

### 🔔 告警推送（钉钉/飞书/企业微信）

支持将成本异常告警推送到钉钉、飞书、企业微信群机器人。

```bash
# 配置通知渠道
curl -X POST http://localhost:8000/api/storage/notifications/configure \
  -d '{
    "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
    "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
  }'

# 发送待处理告警
curl -X POST http://localhost:8000/api/storage/notifications/send-pending
```

### 💾 SQLite 持久化存储

使用 SQLite 存储成本数据、告警、优化建议和预算配置，支持历史查询和分析。

```bash
# 查询成本记录
curl "http://localhost:8000/api/storage/costs?days=30&provider=aws"

# 查询告警
curl "http://localhost:8000/api/storage/alerts?severity=critical"

# 查询优化建议
curl "http://localhost:8000/api/storage/recommendations?priority=high"

# 创建预算
curl -X POST http://localhost:8000/api/storage/budgets \
  -d '{"name": "Monthly AWS", "amount": 10000, "provider": "aws"}'
```

### 🎲 模拟数据生成器

生成真实的多云成本数据用于测试和演示，无需真实云账号凭证。

```bash
# 生成演示数据集（90 天，3 家云厂商）
costlens demo

# 输出示例：
# ✓ Generated 2548 cost records
# ✓ Generated 11 alerts
# ✓ Generated 14 recommendations
# ✓ Created 4 budgets
```

模拟数据特性：
- 支持 AWS、Azure、阿里云三家云厂商
- 模拟真实服务目录和成本范围
- 支持成本趋势、周期性波动
- 可注入异常数据用于测试告警
- 自动生成标签（环境、团队、项目）

## 完整演示

```bash
# 1. 生成演示数据
costlens demo

# 2. 启动 API 服务
costlens server --port 8000

# 3. 查看存储统计
curl http://localhost:8000/api/storage/stats

# 4. 查询成本数据
curl "http://localhost:8000/api/storage/costs?days=30"

# 5. 查看告警
curl http://localhost:8000/api/storage/alerts

# 6. 查看优化建议
curl http://localhost:8000/api/storage/recommendations

# 7. 访问 Prometheus 指标
curl http://localhost:8000/metrics

# 8. 使用 AI 对话
curl -X POST http://localhost:8000/api/chat \
  -d '{"message": "这个月成本是多少？有什么优化建议？"}'
```

详细文档请查看 [FEATURES.md](FEATURES.md)。
