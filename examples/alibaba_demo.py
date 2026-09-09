#!/usr/bin/env python3
"""
阿里云成本分析示例

使用前请确保 .env 文件中配置了阿里云凭证:
    ALIBABA_CLOUD_ACCESS_KEY_ID=your_access_key_id
    ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_access_key_secret
    ALIBABA_CLOUD_REGION=cn-hangzhou
    ENABLED_PROVIDERS=alibaba

运行:
    cd costlens
    source .venv/bin/activate
    python examples/alibaba_demo.py
"""

import asyncio
from datetime import date, timedelta

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from costlens.cloud.alibaba import AlibabaCloudCostConnector
from costlens.analysis.analyzer import CostAnalyzer
from costlens.storage import Storage


async def main():
    console = Console()
    
    console.print(Panel(
        "[bold cyan]CostLens — 阿里云成本分析示例[/bold cyan]",
        title="🚀 CostLens",
    ))

    # 初始化连接器和分析器
    connector = AlibabaCloudCostConnector()
    analyzer = CostAnalyzer()
    storage = Storage("costlens_alibaba.db")
    
    # 查询最近 3 个月
    end = date.today()
    start = end - timedelta(days=90)
    
    console.print(f"\n📅 分析周期: [cyan]{start}[/cyan] 至 [cyan]{end}[/cyan]\n")
    
    # 获取成本数据
    console.print("[dim]正在获取成本数据...[/dim]")
    records = await connector.get_cost_data(start, end, granularity="monthly")
    console.print(f"✅ 获取 [green]{len(records)}[/green] 条成本记录\n")
    
    # 保存到数据库
    storage.save_cost_records(records)
    
    # 获取汇总
    summary = await connector.get_cost_summary(start, end)
    
    console.print(Panel(
        f"[bold cyan]¥{summary.total_cost:,.2f}[/bold cyan]\n"
        f"日均: ¥{summary.daily_avg:,.2f}\n"
        f"服务数: {len(summary.service_breakdown)}",
        title="💰 总成本 (3个月)",
    ))
    
    # 服务分布
    table = Table(title="📊 服务成本分布")
    table.add_column("服务", style="cyan")
    table.add_column("成本", justify="right", style="green")
    table.add_column("占比", justify="right")
    
    for service, cost in list(summary.service_breakdown.items())[:10]:
        pct = (cost / summary.total_cost * 100) if summary.total_cost > 0 else 0
        table.add_row(service, f"¥{cost:,.2f}", f"{pct:.1f}%")
    
    console.print(table)
    
    # 运行完整分析
    console.print("\n[bold]🔍 运行完整分析...[/bold]")
    result = await analyzer.analyze(start, end)
    
    console.print(f"  告警数: {result['alert_count']}")
    console.print(f"  优化建议数: {result['recommendation_count']}")
    console.print(f"  预计可节省: ¥{result['total_potential_savings']:,.2f}")
    
    # 保存分析结果
    storage.save_alerts(result['alerts'])
    storage.save_recommendations(result['recommendations'])
    storage.save_analysis_run(result)
    
    console.print("\n[bold green]✅ 分析完成！数据已保存到 costlens_alibaba.db[/bold green]")
    
    await connector.close()
    await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
