"""Cost report generator for monthly and weekly reports."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from costlens.analysis.analyzer import CostAnalyzer
from costlens.config import Settings, get_settings
from costlens.models.cost import CostRecord

logger = logging.getLogger(__name__)

PROVIDER_NAMES = {
    "alibaba": "阿里云",
    "tencent": "腾讯云",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
}


def _provider_display(name: str) -> str:
    return PROVIDER_NAMES.get(name, name)


def _format_cost(cost: float) -> str:
    if cost >= 10000:
        return f"{cost:,.2f}"
    return f"{cost:,.2f}"


def _pct_change(current: float, previous: float) -> str:
    if previous <= 0:
        if current > 0:
            return "🆕 新增"
        return "—"
    pct = (current - previous) / previous * 100
    if abs(pct) < 0.5:
        return "➡️ 持平"
    if pct > 0:
        return f"🔺 {pct:.1f}%"
    return f"🔻 {abs(pct):.1f}%"


class ReportGenerator:
    """Generate cost reports from real cloud data."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._analyzer = CostAnalyzer(self.settings)

    async def generate_monthly_report(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> str:
        """Generate a monthly cost report in markdown format.

        Args:
            year: Report year. Defaults to current year.
            month: Report month (1-12). Defaults to current month.

        Returns:
            Formatted markdown report string.
        """
        today = date.today()
        if year is None:
            year = today.year
        if month is None:
            month = today.month

        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            period_end = date(year, month + 1, 1) - timedelta(days=1)

        if period_end > today:
            period_end = today

        prev_start = period_start - timedelta(days=(period_end - period_start).days) - timedelta(days=1)
        prev_end = period_start - timedelta(days=1)

        records = await self._fetch_all_records(period_start, period_end)
        prev_records = await self._fetch_all_records(prev_start, prev_end)

        return self._build_monthly_report(
            year, month, period_start, period_end, records, prev_records
        )

    async def generate_weekly_report(
        self,
        ref_date: Optional[date] = None,
        week_offset: int = 0,
    ) -> str:
        """Generate a weekly cost report in markdown format.

        Args:
            ref_date: Reference date. Defaults to today.
            week_offset: 0 = current week, -1 = last week, etc.

        Returns:
            Formatted markdown report string.
        """
        if ref_date is None:
            ref_date = date.today()

        monday = ref_date - timedelta(days=ref_date.weekday()) + timedelta(weeks=week_offset)
        sunday = monday + timedelta(days=6)

        period_start = monday
        period_end = min(sunday, ref_date)

        prev_start = monday - timedelta(days=7)
        prev_end = monday - timedelta(days=1)

        records = await self._fetch_all_records(period_start, period_end, granularity="daily")
        prev_records = await self._fetch_all_records(prev_start, prev_end, granularity="daily")

        return self._build_weekly_report(
            period_start, period_end, records, prev_records
        )

    async def _fetch_all_records(
        self, start: date, end: date, granularity: str = "monthly"
    ) -> list[CostRecord]:
        all_records: list[CostRecord] = []
        for provider in self.settings.get_enabled_providers():
            try:
                connector = await self._analyzer._get_connector(provider.value)
                records = await connector.get_cost_data(start, end, granularity=granularity)
                all_records.extend(records)
            except Exception as exc:
                logger.error("Failed to fetch %s data: %s", provider.value, exc)
        return all_records

    def _build_monthly_report(
        self,
        year: int,
        month: int,
        period_start: date,
        period_end: date,
        records: list[CostRecord],
        prev_records: list[CostRecord],
    ) -> str:
        total_cost = sum(r.cost for r in records)
        prev_total = sum(r.cost for r in prev_records)

        by_provider: dict[str, float] = defaultdict(float)
        by_provider_prev: dict[str, float] = defaultdict(float)
        by_service: dict[str, float] = defaultdict(float)
        by_date: dict[str, float] = defaultdict(float)

        for r in records:
            by_provider[r.provider] += r.cost
            by_service[f"{_provider_display(r.provider)}-{r.service_name}"] += r.cost
            by_date[r.date.isoformat()] += r.cost

        for r in prev_records:
            by_provider_prev[r.provider] += r.cost

        top_services = sorted(by_service.items(), key=lambda x: -x[1])[:10]
        sorted_dates = sorted(by_date.keys())

        days_elapsed = (period_end - period_start).days + 1
        daily_avg = total_cost / max(days_elapsed, 1)
        days_in_month = (period_end - period_start).days + 1
        if period_end == date.today():
            if month == 12:
                full_month_end = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                full_month_end = date(year, month + 1, 1) - timedelta(days=1)
            total_days = (full_month_end - period_start).days + 1
            projected = daily_avg * total_days
        else:
            projected = total_cost
            total_days = days_elapsed

        lines = []
        lines.append(f"## 📊 {year}年{month}月 成本月报")
        lines.append("")
        lines.append(f"**报告周期**: {period_start.strftime('%m/%d')} ~ {period_end.strftime('%m/%d')}（共{days_elapsed}天）")
        lines.append("")

        lines.append(f"### 💰 总成本: {_format_cost(total_cost)} CNY")
        lines.append(f"- 日均支出: {_format_cost(daily_avg)} CNY")
        lines.append(f"- 环比变化: {_pct_change(total_cost, prev_total)}")
        if period_end == date.today():
            lines.append(f"- 月度预估: {_format_cost(projected)} CNY")
        lines.append("")

        lines.append("### 🏢 厂商分布")
        for provider_name in sorted(by_provider.keys(), key=lambda p: -by_provider[p]):
            cost = by_provider[provider_name]
            pct = cost / total_cost * 100 if total_cost > 0 else 0
            prev_cost = by_provider_prev.get(provider_name, 0)
            change = _pct_change(cost, prev_cost)
            lines.append(f"- **{_provider_display(provider_name)}**: {_format_cost(cost)} CNY（{pct:.1f}%）{change}")
        lines.append("")

        lines.append("### 🔝 Top 10 服务")
        for i, (service, cost) in enumerate(top_services, 1):
            pct = cost / total_cost * 100 if total_cost > 0 else 0
            lines.append(f"{i}. {service}: {_format_cost(cost)} CNY（{pct:.1f}%）")
        lines.append("")

        if len(sorted_dates) >= 3:
            lines.append("### 📈 每日支出")
            for d in sorted_dates:
                day_label = date.fromisoformat(d).strftime("%m/%d")
                lines.append(f"- {day_label}: {_format_cost(by_date[d])} CNY")
            lines.append("")

        if daily_avg > 0 and total_days > days_elapsed:
            lines.append("### 🔮 月度预测")
            remaining_days = total_days - days_elapsed
            lines.append(f"- 剩余天数: {remaining_days}天")
            lines.append(f"- 按当前日均预计: {_format_cost(projected)} CNY")
            if prev_total > 0:
                diff = projected - prev_total
                diff_label = "超出" if diff > 0 else "节省"
                lines.append(f"- 对比上月预计{diff_label}: {_format_cost(abs(diff))} CNY")
            lines.append("")

        return "\n".join(lines)

    def _build_weekly_report(
        self,
        period_start: date,
        period_end: date,
        records: list[CostRecord],
        prev_records: list[CostRecord],
    ) -> str:
        total_cost = sum(r.cost for r in records)
        prev_total = sum(r.cost for r in prev_records)

        by_provider: dict[str, float] = defaultdict(float)
        by_provider_prev: dict[str, float] = defaultdict(float)
        by_service: dict[str, float] = defaultdict(float)
        by_date: dict[str, float] = defaultdict(float)
        by_provider_date: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for r in records:
            by_provider[r.provider] += r.cost
            by_service[f"{_provider_display(r.provider)}-{r.service_name}"] += r.cost
            by_date[r.date.isoformat()] += r.cost
            by_provider_date[r.provider][r.date.isoformat()] += r.cost

        for r in prev_records:
            by_provider_prev[r.provider] += r.cost

        top_services = sorted(by_service.items(), key=lambda x: -x[1])[:5]
        sorted_dates = sorted(by_date.keys())

        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        lines = []
        week_num = period_start.isocalendar()[1]
        lines.append(f"## 📊 第{week_num}周 成本周报")
        lines.append("")
        lines.append(f"**报告周期**: {period_start.strftime('%m/%d')}（周一）~ {period_end.strftime('%m/%d')}（{day_names[period_end.weekday()]}）")
        lines.append("")

        lines.append(f"### 💰 本周总成本: {_format_cost(total_cost)} CNY")
        lines.append(f"- 环比变化: {_pct_change(total_cost, prev_total)}")
        if len(sorted_dates) > 0:
            daily_avg = total_cost / len(sorted_dates)
            lines.append(f"- 日均支出: {_format_cost(daily_avg)} CNY")
        lines.append("")

        lines.append("### 🏢 厂商分布")
        for provider_name in sorted(by_provider.keys(), key=lambda p: -by_provider[p]):
            cost = by_provider[provider_name]
            pct = cost / total_cost * 100 if total_cost > 0 else 0
            prev_cost = by_provider_prev.get(provider_name, 0)
            change = _pct_change(cost, prev_cost)
            lines.append(f"- **{_provider_display(provider_name)}**: {_format_cost(cost)} CNY（{pct:.1f}%）{change}")
        lines.append("")

        lines.append("### 🔝 Top 5 服务")
        for i, (service, cost) in enumerate(top_services, 1):
            pct = cost / total_cost * 100 if total_cost > 0 else 0
            lines.append(f"{i}. {service}: {_format_cost(cost)} CNY（{pct:.1f}%）")
        lines.append("")

        if sorted_dates:
            lines.append("### 📈 每日支出")
            for d in sorted_dates:
                dt = date.fromisoformat(d)
                day_name = day_names[dt.weekday()]
                lines.append(f"- {dt.strftime('%m/%d')}（{day_name}）: {_format_cost(by_date[d])} CNY")
            lines.append("")

        if sorted_dates:
            max_date = max(sorted_dates, key=lambda d: by_date[d])
            min_date = min(sorted_dates, key=lambda d: by_date[d])
            lines.append("### 📋 小结")
            lines.append(f"- 最高支出日: {date.fromisoformat(max_date).strftime('%m/%d')}（{_format_cost(by_date[max_date])} CNY）")
            if len(sorted_dates) > 1:
                lines.append(f"- 最低支出日: {date.fromisoformat(min_date).strftime('%m/%d')}（{_format_cost(by_date[min_date])} CNY）")
            lines.append("")

        return "\n".join(lines)

    async def close(self) -> None:
        await self._analyzer.close()
