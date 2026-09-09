# CostLens 扩展功能

本文档介绍 CostLens 的四个核心扩展功能。

## 1. Prometheus 指标导出

### 概述
提供 `/metrics` 端点，导出 Prometheus 格式的成本指标，可集成到 Grafana 进行可视化。

### 指标类型

- **costlens_cloud_cost_total** — 各云厂商总成本
- **costlens_cloud_cost_daily_avg** — 日均成本
- **costlens_cloud_service_cost** — 按服务分类的成本（Top 10）
- **costlens_cloud_cost_month_to_date** — 月初至今成本
- **costlens_budget_utilization_percent** — 预算使用率
- **costlens_alerts_total** — 告警数量（按严重级别）
- **costlens_recommendations_total** — 优化建议数量
- **costlens_potential_savings_total** — 预计可节省金额

### 使用方式

```bash
# 启动服务
costlens server --port 8000

# 访问指标端点
curl http://localhost:8000/metrics
```

### Prometheus 配置

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'costlens'
    scrape_interval: 300s  # 5分钟采集一次
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### Grafana Dashboard 示例

```json
{
  "panels": [
    {
      "title": "Monthly Cost by Provider",
      "type": "stat",
      "targets": [
        {
          "expr": "costlens_cloud_cost_total",
          "legendFormat": "{{provider}}"
        }
      ]
    },
    {
      "title": "Daily Average Cost",
      "type": "gauge",
      "targets": [
        {
          "expr": "costlens_cloud_cost_daily_avg"
        }
      ]
    },
    {
      "title": "Top Services by Cost",
      "type": "table",
      "targets": [
        {
          "expr": "topk(10, costlens_cloud_service_cost)",
          "legendFormat": "{{service}}"
        }
      ]
    }
  ]
}
```

## 2. 告警推送（钉钉/飞书/企业微信）

### 概述
支持将成本异常告警推送到钉钉、飞书、企业微信群机器人。

### 支持的渠道

- **钉钉 (DingTalk)** — 支持加签验证
- **飞书 (Feishu/Lark)** — 支持交互式卡片消息
- **企业微信 (WeChat Work)** — 支持 Markdown 格式

### 配置方式

#### 方式一：环境变量

```bash
# .env 文件
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_WEBHOOK_SECRET=SECxxx  # 可选，用于加签

FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx

WECHAT_WORK_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

#### 方式二：API 配置

```bash
# 配置通知渠道
curl -X POST http://localhost:8000/api/storage/notifications/configure \
  -H "Content-Type: application/json" \
  -d '{
    "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
    "dingtalk_secret": "SECxxx",
    "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
    "wechat_work_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  }'

# 发送待处理告警
curl -X POST http://localhost:8000/api/storage/notifications/send-pending
```

### 告警消息格式

#### 钉钉消息示例

```markdown
### 🟡 EC2 Cost Spike

**EC2 cost increased by 50% in the last 24 hours**

- 云厂商: aws
- 严重程度: warning
- 当前值: 1500.00 USD
- 阈值: 1000.00 USD
- 时间: 2024-01-15 10:30:00
```

#### 飞书卡片消息

飞书使用交互式卡片，包含颜色编码：
- 🔴 红色 — Critical 级别
- 🟡 黄色 — Warning 级别
- 🔵 蓝色 — Info 级别

### 代码示例

```python
from costlens.notifications import NotificationManager, DingTalkNotifier
from costlens.models.alert import Alert, AlertSeverity, AlertType

# 创建通知管理器
manager = NotificationManager()
manager.add_dingtalk(
    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=xxx",
    secret="SECxxx"
)
manager.add_feishu("https://open.feishu.cn/open-apis/bot/v2/hook/xxx")

# 创建告警
alert = Alert(
    alert_type=AlertType.COST_ANOMALY,
    severity=AlertSeverity.WARNING,
    title="EC2 Cost Spike",
    message="EC2 cost increased by 50%",
    provider="aws",
    current_value=1500.0,
    threshold_value=1000.0,
)

# 发送通知
import asyncio
asyncio.run(manager.notify(alert))
```

## 3. SQLite 持久化存储

### 概述
使用 SQLite 存储成本数据、告警、优化建议和预算配置，支持历史查询和分析。

### 数据库表结构

- **cost_records** — 成本明细记录
- **alerts** — 告警历史
- **recommendations** — 优化建议
- **budgets** — 预算配置
- **analysis_runs** — 分析运行历史

### 使用方式

#### CLI 命令

```bash
# 运行分析并保存到数据库
costlens analyze --days 30

# 查询存储统计
curl http://localhost:8000/api/storage/stats
```

#### API 端点

```bash
# 查询成本记录
curl "http://localhost:8000/api/storage/costs?days=30&provider=aws"

# 查询日成本汇总
curl "http://localhost:8000/api/storage/costs/daily?days=30"

# 查询服务成本分布
curl "http://localhost:8000/api/storage/costs/services?days=30"

# 查询告警
curl "http://localhost:8000/api/storage/alerts?days=30&severity=critical"

# 确认告警
curl -X POST http://localhost:8000/api/storage/alerts/123/acknowledge

# 查询优化建议
curl "http://localhost:8000/api/storage/recommendations?priority=high"

# 创建预算
curl -X POST http://localhost:8000/api/storage/budgets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Monthly AWS",
    "amount": 10000,
    "currency": "USD",
    "period": "monthly",
    "provider": "aws"
  }'

# 查询预算列表
curl http://localhost:8000/api/storage/budgets

# 删除预算
curl -X DELETE http://localhost:8000/api/storage/budgets/Monthly%20AWS

# 查询分析历史
curl http://localhost:8000/api/storage/analysis-runs
```

#### Python API

```python
from datetime import date, timedelta
from costlens.storage import get_storage

storage = get_storage("costlens.db")

# 查询最近 30 天成本
end = date.today()
start = end - timedelta(days=30)
records = storage.get_cost_records(start, end, provider="aws")

# 查询日成本汇总
daily_totals = storage.get_daily_totals(start, end)

# 查询服务成本分布
service_totals = storage.get_service_totals(start, end)

# 查询未确认的 critical 告警
alerts = storage.get_alerts(severity="critical", acknowledged=False)

# 确认告警
storage.acknowledge_alert(alert_id=123)

# 查询高优先级优化建议
recs = storage.get_recommendations(priority="high")

# 获取预计可节省总额
total_savings = storage.get_total_potential_savings()
```

### 数据库维护

```bash
# 查看数据库文件
ls -lh costlens.db

# 使用 sqlite3 直接查询
sqlite3 costlens.db "SELECT * FROM cost_records LIMIT 10;"

# 备份数据库
cp costlens.db costlens.db.backup

# 清理旧数据（保留最近 90 天）
sqlite3 costlens.db "DELETE FROM cost_records WHERE record_date < date('now', '-90 days');"
```

## 4. 模拟数据生成器

### 概述
生成真实的多云成本数据用于测试和演示，无需真实云账号凭证。

### 特性

- 支持 AWS、Azure、阿里云三家云厂商
- 模拟真实服务目录和成本范围
- 支持成本趋势、周期性波动
- 可注入异常数据用于测试告警
- 自动生成标签（环境、团队、项目）

### 使用方式

#### CLI 命令

```bash
# 生成演示数据集（90 天，3 家云厂商）
costlens demo

# 指定数据库路径
costlens demo --db my_demo.db
```

输出示例：
```
Demo Dataset Generated
✓ Generated 4500 cost records
✓ Generated 12 alerts
✓ Generated 8 recommendations
✓ Created 4 budgets

Database: costlens_demo.db

📊 Storage Stats
┌──────────────────┬───────┐
│ Table            │ Count │
├──────────────────┼───────┤
│ cost_records     │ 4500  │
│ alerts           │ 12    │
│ recommendations  │ 8     │
│ budgets          │ 4     │
│ analysis_runs    │ 0     │
└──────────────────┴───────┘
```

#### Python API

```python
from costlens.mock_data import MockDataProvider, generate_demo_dataset

# 生成单云厂商数据
provider = MockDataProvider(seed=42)
records = provider.generate_daily_records(
    provider="aws",
    days=30,
    inject_anomaly=True,  # 注入异常
    anomaly_day=15,       # 第 15 天异常
    anomaly_multiplier=3.0  # 成本增加 3 倍
)

# 生成多云数据
all_records = provider.generate_multi_cloud_data(
    providers=["aws", "azure", "alibaba"],
    days=60,
    inject_anomaly=True
)

# 生成完整演示数据集
result = generate_demo_dataset("costlens_demo.db")
print(f"Generated {result['records_generated']} records")
```

#### MockCloudConnector

```python
from costlens.mock_data import MockCloudConnector
from datetime import date, timedelta

# 创建 mock 连接器
connector = MockCloudConnector(provider="aws", seed=42)

# 获取成本数据（与真实连接器接口一致）
end = date.today()
start = end - timedelta(days=30)
records = await connector.get_cost_data(start, end)

# 获取成本汇总
summary = await connector.get_cost_summary(start, end)
print(f"Total cost: {summary['total_cost']:.2f}")

# 获取服务成本分布
breakdown = await connector.get_service_breakdown(start, end)
for service, cost in breakdown.items():
    print(f"{service}: {cost:.2f}")
```

### 模拟服务目录

#### AWS 服务（日成本范围）

- Amazon EC2: $200 - $800
- Amazon S3: $50 - $200
- Amazon RDS: $80 - $400
- AWS Lambda: $10 - $80
- Amazon CloudFront: $30 - $150
- Amazon ECS: $30 - $100
- 等 12 个服务

#### Azure 服务

- Virtual Machines: $150 - $600
- Storage Accounts: $30 - $120
- Azure SQL Database: $60 - $300
- Azure Functions: $5 - $40
- 等 8 个服务

#### 阿里云服务

- 云服务器 ECS: ¥100 - ¥500
- 对象存储 OSS: ¥20 - ¥80
- 云数据库 RDS: ¥40 - ¥200
- 函数计算: ¥5 - ¥30
- 等 8 个服务

### 数据特征

- **周期性波动** — 周末计算资源成本降低 20-40%
- **增长趋势** — 每日增长 0.2%，模拟业务增长
- **随机噪声** — ±10% 的随机波动
- **异常注入** — 可在指定日期注入成本突增

### 完整演示流程

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
```

## 完整集成示例

### 场景：成本异常检测与告警

```python
import asyncio
from datetime import date, timedelta
from costlens.analysis.analyzer import CostAnalyzer
from costlens.storage import get_storage
from costlens.notifications import NotificationManager

async def detect_and_notify():
    # 初始化
    analyzer = CostAnalyzer()
    storage = get_storage()
    notifier = NotificationManager()
    notifier.add_dingtalk("https://oapi.dingtalk.com/robot/send?access_token=xxx")

    # 分析最近 30 天数据
    end = date.today()
    start = end - timedelta(days=30)
    result = await analyzer.analyze(start, end)

    # 保存到数据库
    storage.save_analysis_run(result)
    storage.save_alerts(result["alerts"])
    storage.save_recommendations(result["recommendations"])

    # 发送告警通知
    if result["alerts"]:
        await notifier.notify_batch(result["alerts"])
        print(f"Sent {len(result['alerts'])} alerts")

    # 输出摘要
    print(f"Total cost: {result['total_cost']:.2f}")
    print(f"Alerts: {result['alert_count']}")
    print(f"Recommendations: {result['recommendation_count']}")
    print(f"Potential savings: {result['total_potential_savings']:.2f}")

    await analyzer.close()

asyncio.run(detect_and_notify())
```

### 场景：Grafana Dashboard

```bash
# 1. 启动 CostLens
costlens server --port 8000

# 2. 配置 Prometheus 采集
# prometheus.yml
scrape_configs:
  - job_name: 'costlens'
    static_configs:
      - targets: ['localhost:8000']

# 3. 启动 Prometheus
prometheus --config.file=prometheus.yml

# 4. 在 Grafana 中添加 Prometheus 数据源
# URL: http://localhost:9090

# 5. 创建 Dashboard，使用以下查询：
# - 总成本：costlens_cloud_cost_total
# - 日均成本：costlens_cloud_cost_daily_avg
# - Top 服务：topk(10, costlens_cloud_service_cost)
# - 告警数：costlens_alerts_total
```

## 测试验证

所有新功能均已通过测试（57 个测试用例）：

```bash
# 运行所有测试
pytest tests/ -v

# 运行存储测试
pytest tests/test_storage.py -v

# 运行通知测试
pytest tests/test_notifications.py -v

# 运行模拟数据测试
pytest tests/test_mock_data.py -v
```

测试结果：
- ✅ 成本记录存储与查询
- ✅ 告警持久化与确认
- ✅ 优化建议存储
- ✅ 预算管理
- ✅ 钉钉/飞书/企业微信消息格式
- ✅ 模拟数据生成
- ✅ Prometheus 指标导出
- ✅ API 端点
