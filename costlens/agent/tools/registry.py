"""Tool registry for CostLens agent - defines callable tools for LLM."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Coroutine

from costlens.analysis.analyzer import CostAnalyzer
from costlens.models.budget import Budget

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """A tool definition that the LLM can call."""
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Coroutine[Any, Any, Any]]

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry of all tools available to the CostLens agent."""

    def __init__(self, analyzer: CostAnalyzer) -> None:
        self.analyzer = analyzer
        self._tools: dict[str, Tool] = {}
        self._budgets: list[Budget] = []
        self._register_default_tools()

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict]:
        return [t.to_openai_schema() for t in self._tools.values()]

    async def execute(self, name: str, arguments: dict) -> str:
        tool = self.get_tool(name)
        if not tool:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
        try:
            result = await tool.handler(**arguments)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            logger.error("Tool %s execution failed: %s", name, exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def set_budgets(self, budgets: list[Budget]) -> None:
        self._budgets = budgets

    def _register_default_tools(self) -> None:
        self._register_cost_summary_tool()
        self._register_anomaly_detection_tool()
        self._register_recommendations_tool()
        self._register_trend_analysis_tool()
        self._register_forecast_tool()
        self._register_budget_check_tool()
        self._register_multi_cloud_summary_tool()
        self._register_monthly_report_tool()
        self._register_weekly_report_tool()
        self._register_balance_query_tool()
        self._register_db_cost_query_tool()
        self._register_monthly_comparison_tool()

    def _register_cost_summary_tool(self) -> None:
        async def handler(days: int = 30, provider: str = "") -> dict:
            end = date.today()
            start = end - timedelta(days=days)
            if provider:
                connector = await self.analyzer._get_connector(provider)
                summary = await connector.get_cost_summary(start, end)
                return summary.model_dump()
            return await self.analyzer.get_multi_cloud_summary(start, end)

        self.register(Tool(
            name="get_cost_summary",
            description="获取最近N天的实时云成本概览（调用云厂商API）。仅用于查询今天/实时/当前数据，不适用于历史月份查询。历史月份请用 query_monthly_cost_from_db。",
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "查询最近多少天的数据，默认30天",
                    },
                    "provider": {
                        "type": "string",
                        "description": "云厂商标识 (aws/azure/gcp/alibaba)，留空则查询所有",
                        "enum": ["aws", "azure", "gcp", "alibaba", ""],
                    },
                },
            },
            handler=handler,
        ))

    def _register_anomaly_detection_tool(self) -> None:
        async def handler(days: int = 30) -> dict:
            end = date.today()
            start = end - timedelta(days=days)
            all_records = []
            for provider in self.analyzer.settings.get_enabled_providers():
                connector = await self.analyzer._get_connector(provider.value)
                records = await connector.get_cost_data(start, end)
                all_records.extend(records)
            alerts = self.analyzer.anomaly_detector.detect_anomalies(all_records)
            return {
                "anomalies": [a.model_dump() for a in alerts],
                "count": len(alerts),
            }

        self.register(Tool(
            name="detect_anomalies",
            description="检测成本数据中的异常，包括突增、突降和偏离历史趋势的情况。",
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "分析最近多少天的数据，默认30天",
                    },
                },
            },
            handler=handler,
        ))

    def _register_recommendations_tool(self) -> None:
        async def handler(days: int = 30, priority: str = "") -> dict:
            end = date.today()
            start = end - timedelta(days=days)
            all_recommendations = []
            for provider in self.analyzer.settings.get_enabled_providers():
                connector = await self.analyzer._get_connector(provider.value)
                records = await connector.get_cost_data(start, end)
                recs = self.analyzer.optimizer.generate_recommendations(records, provider.value)
                all_recommendations.extend(recs)
            if priority:
                all_recommendations = [
                    r for r in all_recommendations if r.priority.value == priority
                ]
            total_savings = sum(r.estimated_saving for r in all_recommendations)
            return {
                "recommendations": [r.model_dump() for r in all_recommendations],
                "count": len(all_recommendations),
                "total_potential_savings": round(total_savings, 2),
            }

        self.register(Tool(
            name="get_recommendations",
            description="获取成本优化建议，包括预留实例、闲置资源、存储分层等。",
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "分析最近多少天的数据，默认30天",
                    },
                    "priority": {
                        "type": "string",
                        "description": "按优先级筛选 (high/medium/low)",
                        "enum": ["high", "medium", "low", ""],
                    },
                },
            },
            handler=handler,
        ))

    def _register_trend_analysis_tool(self) -> None:
        async def handler(days: int = 30) -> dict:
            end = date.today()
            start = end - timedelta(days=days)
            all_records = []
            for provider in self.analyzer.settings.get_enabled_providers():
                connector = await self.analyzer._get_connector(provider.value)
                records = await connector.get_cost_data(start, end)
                all_records.extend(records)
            trend = self.analyzer.trend_analyzer.analyze_daily_trend(all_records)
            prev_start = start - timedelta(days=days)
            prev_end = start - timedelta(days=1)
            prev_records = []
            for provider in self.analyzer.settings.get_enabled_providers():
                connector = await self.analyzer._get_connector(provider.value)
                prev_records.extend(await connector.get_cost_data(prev_start, prev_end))
            pop_trends = self.analyzer.trend_analyzer.analyze_period_over_period(
                all_records, prev_records
            )
            return {
                "daily_trend": trend,
                "period_over_period": [t.model_dump() for t in pop_trends[:10]],
            }

        self.register(Tool(
            name="analyze_trends",
            description="分析成本趋势，包括日趋势、移动平均和环比对比。",
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "分析最近多少天的数据，默认30天",
                    },
                },
            },
            handler=handler,
        ))

    def _register_forecast_tool(self) -> None:
        async def handler(forecast_days: int = 30) -> dict:
            end = date.today()
            start = end - timedelta(days=90)
            all_records = []
            for provider in self.analyzer.settings.get_enabled_providers():
                connector = await self.analyzer._get_connector(provider.value)
                records = await connector.get_cost_data(start, end)
                all_records.extend(records)
            return self.analyzer.trend_analyzer.forecast(all_records, forecast_days)

        self.register(Tool(
            name="forecast_cost",
            description="基于历史数据预测未来成本。使用线性回归模型。",
            parameters={
                "type": "object",
                "properties": {
                    "forecast_days": {
                        "type": "integer",
                        "description": "预测未来多少天，默认30天",
                    },
                },
            },
            handler=handler,
        ))

    def _register_budget_check_tool(self) -> None:
        async def handler() -> dict:
            if not self._budgets:
                return {"message": "未配置预算", "budgets": []}
            end = date.today()
            start = end - timedelta(days=30)
            all_records = []
            for provider in self.analyzer.settings.get_enabled_providers():
                connector = await self.analyzer._get_connector(provider.value)
                records = await connector.get_cost_data(start, end)
                all_records.extend(records)
            budgets = self.analyzer.budget_analyzer.get_budget_status(
                self._budgets, all_records
            )
            alerts = self.analyzer.budget_analyzer.evaluate_budgets(
                self._budgets, all_records
            )
            return {
                "budgets": [b.model_dump() for b in budgets],
                "alerts": [a.model_dump() for a in alerts],
            }

        self.register(Tool(
            name="check_budgets",
            description="检查当前预算执行情况和超支告警。",
            parameters={
                "type": "object",
                "properties": {},
            },
            handler=handler,
        ))

    def _register_multi_cloud_summary_tool(self) -> None:
        async def handler(days: int = 30) -> dict:
            end = date.today()
            start = end - timedelta(days=days)
            return await self.analyzer.get_multi_cloud_summary(start, end)

        self.register(Tool(
            name="get_multi_cloud_summary",
            description="获取所有已配置云厂商的成本汇总。",
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "查询最近多少天的数据，默认30天",
                    },
                },
            },
            handler=handler,
        ))

    def _register_balance_query_tool(self) -> None:
        async def handler() -> dict:
            """Query account balance from all enabled providers."""
            results = {}
            for provider in self.analyzer.settings.get_enabled_providers():
                try:
                    connector = await self.analyzer._get_connector(provider.value)
                    balance = await connector.get_account_balance()
                    results[provider.value] = balance
                except Exception as exc:
                    results[provider.value] = {"error": str(exc)}
            return results

        self.register(Tool(
            name="get_account_balance",
            description="查询所有云厂商的账户余额和信用额度信息。",
            parameters={
                "type": "object",
                "properties": {},
            },
            handler=handler,
        ))

    def _register_db_cost_query_tool(self) -> None:
        """Query cost data from local database (fast, complete)."""
        async def handler(month: int, year: int = 0, provider: str = "") -> dict:
            from costlens.db import get_backend
            from datetime import datetime
            if year == 0:
                year = datetime.now().year
            backend = get_backend()
            db = backend.raw_connect()
            def _a(sql):
                return backend.adapt_sql(sql)

            period_start = f"{year}-{month:02d}-01"
            if month == 12:
                period_end = f"{year + 1}-01-01"
            else:
                period_end = f"{year}-{month + 1:02d}-01"

            # Deduplicate by granularity: prefer 'daily' over 'monthly' per provider
            # This avoids double-counting when both granularities exist
            base_where = "WHERE record_date >= ? AND record_date < ?"
            base_params = [period_start, period_end]

            # Check which granularities exist per provider
            check_query = _a(f"SELECT provider, granularity, COUNT(*) as cnt FROM cost_records {base_where} GROUP BY provider, granularity")
            cur = db.execute(check_query, base_params)
            provider_granularities = {}
            for row in cur.fetchall():
                p = row[0]
                if p not in provider_granularities:
                    provider_granularities[p] = []
                provider_granularities[p].append(row[1])

            results = []
            total_cost = 0

            for p, grans in provider_granularities.items():
                if provider and p != provider:
                    continue

                has_daily = "daily" in grans
                has_monthly = "monthly" in grans

                if has_daily and has_monthly:
                    # Smart dedup: daily data + monthly-only services (daily API misses some products)
                    daily_q = _a(f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0), 2) FROM cost_records {base_where} AND provider = ? AND granularity = 'daily'")
                    daily_row = db.execute(daily_q, base_params + [p]).fetchone()
                    daily_cnt = daily_row[0] or 0
                    daily_total = daily_row[1] or 0

                    monthly_only_q = _a(f"""SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0), 2) FROM cost_records
                        {base_where} AND provider = ? AND granularity = 'monthly'
                        AND service_name NOT IN (
                            SELECT DISTINCT service_name FROM cost_records
                            {base_where} AND provider = ? AND granularity = 'daily'
                        )""")
                    mo_row = db.execute(monthly_only_q, base_params + [p] + base_params + [p]).fetchone()
                    mo_cnt = mo_row[0] or 0
                    mo_total = mo_row[1] or 0

                    cnt = daily_cnt + mo_cnt
                    total = round(daily_total + mo_total, 2)
                    results.append({"provider": p, "record_count": cnt, "total_cost": total, "granularity": "daily+monthly-only"})
                    total_cost += total

                elif has_daily:
                    gran_where = f"{base_where} AND provider = ? AND granularity = 'daily'"
                    q = _a(f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0), 2) FROM cost_records {gran_where}")
                    row = db.execute(q, base_params + [p]).fetchone()
                    cnt = row[0] or 0
                    total = row[1] or 0
                    results.append({"provider": p, "record_count": cnt, "total_cost": total, "granularity": "daily"})
                    total_cost += total

                else:
                    gran_where = f"{base_where} AND provider = ? AND granularity = 'monthly'"
                    q = _a(f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0), 2) FROM cost_records {gran_where}")
                    row = db.execute(q, base_params + [p]).fetchone()
                    cnt = row[0] or 0
                    total = row[1] or 0
                    results.append({"provider": p, "record_count": cnt, "total_cost": total, "granularity": "monthly"})
                    total_cost += total

            # Top services - smart dedup: daily services + monthly-only services
            all_top_services = []
            for p, grans in provider_granularities.items():
                if provider and p != provider:
                    continue
                has_daily = "daily" in grans
                has_monthly = "monthly" in grans

                if has_daily:
                    svc_query = _a(f"SELECT service_name, ROUND(SUM(cost), 2) as total FROM cost_records {base_where} AND provider = ? AND granularity = 'daily' GROUP BY service_name ORDER BY total DESC LIMIT 10")
                    cur2 = db.execute(svc_query, base_params + [p])
                    daily_svc_names = set()
                    for r in cur2.fetchall():
                        all_top_services.append({"service": r[0], "cost": r[1], "provider": p})
                        daily_svc_names.add(r[0])

                if has_monthly:
                    mo_svc_query = _a(f"""SELECT service_name, ROUND(SUM(cost), 2) as total FROM cost_records
                        {base_where} AND provider = ? AND granularity = 'monthly'
                        AND service_name NOT IN (
                            SELECT DISTINCT service_name FROM cost_records
                            {base_where} AND provider = ? AND granularity = 'daily'
                        )
                        GROUP BY service_name ORDER BY total DESC LIMIT 10""")
                    cur3 = db.execute(mo_svc_query, base_params + [p] + base_params + [p])
                    for r in cur3.fetchall():
                        all_top_services.append({"service": r[0], "cost": r[1], "provider": p})

            all_top_services.sort(key=lambda x: -x["cost"])
            top_services = all_top_services[:10]

            db.close()

            return {
                "year": year,
                "month": month,
                "providers": results,
                "total_cost": round(total_cost, 2),
                "currency": "CNY",
                "top_services": top_services,
                "source": "database",
            }

        self.register(Tool(
            name="query_monthly_cost_from_db",
            description="从本地数据库查询指定月份的公有云成本数据。返回总成本、各厂商明细、Top10产品排名。适用于查询历史月份的总成本、产品排名、Top N、成本明细等所有历史数据查询。",
            parameters={
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "年份，默认当前年(2026)，可不传", "default": 0},
                    "month": {"type": "integer", "description": "月份 1-12，例如 8", "minimum": 1, "maximum": 12},
                    "provider": {"type": "string", "description": "云厂商标识 alibaba/tencent，留空查全部", "enum": ["alibaba", "tencent", ""]},
                },
                "required": ["month"],
            },
            handler=handler,
        ))

    def _register_monthly_comparison_tool(self) -> None:
        async def handler(year: int = 0, month: int = 0) -> dict:
            """Generate monthly cost comparison with YoY and MoM analysis."""
            from costlens.analysis.monthly_comparison import MonthlyComparison
        
            comparison = MonthlyComparison(self.analyzer.settings)
            try:
                report = await comparison.generate_comparison_report(
                    year if year > 0 else None,
                    month if month > 0 else None,
                )
                return {"report": report, "type": "monthly_comparison"}
            finally:
                await comparison.close()

        self.register(Tool(
            name="generate_monthly_comparison",
            description="生成月度成本对比分析报告，包含环比和同比分析。",
            parameters={
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "年份，默认当前年份",
                    },
                    "month": {
                        "type": "integer",
                        "description": "月份（1-12），默认当前月",
                    },
                },
            },
            handler=handler,
        ))

    def _register_monthly_report_tool(self) -> None:
        async def handler(year: int = 0, month: int = 0) -> dict:
            from costlens.reports import ReportGenerator
            generator = ReportGenerator(self.analyzer.settings)
            try:
                report = await generator.generate_monthly_report(
                    year if year > 0 else None,
                    month if month > 0 else None,
                )
                return {"report": report, "type": "monthly"}
            finally:
                await generator.close()

        self.register(Tool(
            name="generate_monthly_report",
            description="生成成本月报，包含总成本、厂商分布、Top服务、每日支出趋势和环比分析。",
            parameters={
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "年份，默认当前年份",
                    },
                    "month": {
                        "type": "integer",
                        "description": "月份（1-12），默认当前月",
                    },
                },
            },
            handler=handler,
        ))

    def _register_weekly_report_tool(self) -> None:
        async def handler(week_offset: int = 0) -> dict:
            from costlens.reports import ReportGenerator
            generator = ReportGenerator(self.analyzer.settings)
            try:
                report = await generator.generate_weekly_report(
                    week_offset=week_offset,
                )
                return {"report": report, "type": "weekly"}
            finally:
                await generator.close()

        self.register(Tool(
            name="generate_weekly_report",
            description="生成成本周报，包含本周总成本、厂商分布、Top服务、每日支出和环比分析。week_offset=0是本周，-1是上周。",
            parameters={
                "type": "object",
                "properties": {
                    "week_offset": {
                        "type": "integer",
                        "description": "周偏移量，0=本周，-1=上周，-2=上上周",
                    },
                },
            },
            handler=handler,
        ))
