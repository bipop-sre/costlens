# 资源级账单明细功能

## 概述

CostLens 现已支持资源级（实例级）账单明细，可以追踪每个云资源实例的每日成本消耗。

## 功能特性

### 1. 实例级数据追踪
- **阿里云**: 通过 QueryInstanceBill API 获取实例级账单数据
- **腾讯云**: 从账单明细中提取 ResourceId 和 ResourceName
- 每条账单记录包含 `instance_id` 和 `instance_name` 字段

### 2. Web Dashboard 增强
在"每日明细"标签页新增"资源明细"面板：
- 按日期、云厂商、服务名、实例 ID/名称分组展示
- 支持搜索过滤（实例 ID 或名称）
- 显示实例总数和总成本
- 可展开查看每个实例的每日成本明细

### 3. 数据模型扩展
`CostRecord` 新增字段：
```python
instance_id: str = ""      # 资源实例 ID
instance_name: str = ""    # 资源实例名称
```

### 4. 数据库 Schema 更新
`cost_records` 表新增列：
- `instance_id VARCHAR(256) DEFAULT ''`
- `instance_name VARCHAR(256) DEFAULT ''`
- 唯一约束更新为包含 `instance_id`

## 部署步骤

### 1. 数据库迁移

**OceanBase/MySQL:**
```bash
# 在 Kubernetes Pod 中执行
kubectl exec -it costlens-<pod-name> -n sys -- python3 -c "
from costlens.db import DatabaseBackend
backend = DatabaseBackend('oceanbase')
backend.migrate_add_instance_fields()
"
```

**SQLite (本地开发):**
```bash
python3 -c "
from costlens.db import DatabaseBackend
backend = DatabaseBackend('sqlite')
backend.migrate_add_instance_fields()
"
```

### 2. 重新部署应用

```bash
# 提交代码
git add .
git commit -m "feat: 支持资源级账单明细"
git push origin main

# K8s 自动重新部署，或手动触发
kubectl rollout restart deployment/costlens -n sys
```

### 3. 触发数据同步

通过 Web Dashboard 点击"同步数据"按钮，或等待定时任务执行（每小时一次）。

## 使用方法

### Web Dashboard

1. 访问 CostLens Dashboard
2. 点击"每日明细"标签页
3. 在"资源明细"面板中：
   - 选择月份和云厂商
   - 使用搜索框过滤实例
   - 点击展开查看实例详情

### API 接口

```bash
# 获取实例级每日账单数据
curl -X GET "http://localhost:8000/api/daily/instances?year=2026&month=9&provider=alibaba" \
  -H "Authorization: Bearer YOUR_TOKEN"

# 响应示例
{
  "instances": [
    {
      "date": "2026-09-11",
      "provider": "alibaba",
      "service_name": "云服务器 ECS",
      "instance_id": "i-bp1a2b3c4d5e6f",
      "instance_name": "web-server-01",
      "cost": 125.50,
      "currency": "CNY"
    }
  ],
  "total": 156
}
```

## 数据来源

### 阿里云
- **API**: `QueryInstanceBill`
- **粒度**: 日级
- **字段**: InstanceID, InstanceName, ProductName, PretaxAmount
- **限制**: 每次最多 300 条，支持分页

### 腾讯云
- **API**: `DescribeBillDetail`
- **粒度**: 日级（从月度明细聚合）
- **字段**: ResourceId, ResourceName, BusinessCodeName, ComponentSet
- **限制**: 每次最多 100 条，支持分页

## 性能考虑

- 实例级数据量比服务级大 10-100 倍
- 建议按需查询特定月份和云厂商
- Web Dashboard 默认限制显示前 200 条记录
- 数据库索引已优化查询性能

## 兼容性

- 旧数据（无 instance_id）自动归类为聚合记录
- 新数据同步时自动填充实例信息
- 不影响现有的服务级成本分析功能

## 故障排查

### 问题：资源明细面板显示"暂无数据"

**解决方案:**
1. 确认已执行数据库迁移
2. 触发数据同步（点击"同步数据"按钮）
3. 检查云厂商 API 凭证是否正确
4. 查看应用日志：`kubectl logs costlens-<pod-name> -n sys`

### 问题：实例名称显示为空

**原因:** 云厂商 API 可能不返回实例名称，或实例已被删除

**解决方案:** 这是正常现象，可以通过实例 ID 在云控制台查询详细信息

## 未来增强

- [ ] 支持按标签过滤实例
- [ ] 实例成本趋势图表
- [ ] 导出实例级账单为 CSV/Excel
- [ ] 实例成本异常告警
- [ ] 支持更多云厂商（AWS、Azure、GCP）
