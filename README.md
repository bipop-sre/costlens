# CostLens AI Agent 🚀

AI 驱动的多云成本监控与优化智能体，帮助企业实时监测公有云支出、发现异常、优化资源。

## 核心能力

- **多云成本聚合** — 统一查看阿里云 / 腾讯云成本数据
- **智能异常检测** — 自动发现成本突增与异常偏离
- **成本趋势分析** — 日趋势、移动平均、环比同比、成本预测
- **AI 优化建议** — 预留实例、闲置资源清理、存储分层、架构优化
- **预算管理** — 预算执行监控与超支预警
- **自然语言交互** — 通过对话方式查询和分析成本
- **企业微信 Bot** — 直接在企业微信中对话查询
- **告警推送** — 支持钉钉 / 飞书 / 企业微信通知

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
| `ENABLED_PROVIDERS` | 启用的云厂商：`alibaba,tencent` |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` / `_SECRET` | 阿里云 AccessKey |
| `TENCENT_CLOUD_SECRET_ID` / `_KEY` | 腾讯云凭证 |

### 运行

```bash
# Web + Bot 统一启动（推荐）
python run_web.py          # Dashboard: http://localhost:8080

# 仅 Bot
python run_bot.py

# 交互对话
costlens chat

# API 服务
costlens server --port 8000

# 一次性分析
costlens analyze --days 30

# 演示模式（生成演示数据后启动）
costlens demo && python run_web.py
```

## API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | AI 对话（支持 SSE 流式） |
| `/api/cost/summary` | GET | 成本汇总 |
| `/api/cost/anomalies` | GET | 异常检测 |
| `/api/cost/recommendations` | GET | 优化建议 |
| `/api/budgets` | POST | 预算管理 |
| `/health` | GET | 健康检查 |
| `/metrics` | GET | Prometheus 指标 |

## 技术栈

Python 3.14+ · FastAPI · OpenAI API · NumPy · alibabacloud-bssopenapi · tencentcloud-sdk-python · wecom-aibot-sdk · Rich

## 开发

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check costlens/ && ruff format costlens/
```

## 部署

```bash
docker build -t costlens:latest .
```

支持 Docker / Kubernetes (Helm) 部署，存储支持 SQLite 和 OceanBase。详见 [部署文档](docs/)。

## 相关文档

- [功能详情](FEATURES.md) — 完整功能描述与扩展能力
- [项目总结](SUMMARY.md) — 架构设计与实现总结

## License

MIT
