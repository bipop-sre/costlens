"""CostLens entry points."""

from __future__ import annotations

import asyncio
import logging
import sys

from costlens.config import get_settings


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def interactive_chat() -> None:
    """Run interactive CLI chat session."""
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    from costlens.agent.core import CostLensAgent

    console = Console()
    settings = get_settings()
    agent = CostLensAgent(settings)

    console.print(Panel(
        "[bold cyan]CostLens AI Agent[/bold cyan]\n"
        "多云成本监控与优化智能体\n\n"
        f"模型: {settings.openai_model}\n"
        f"云厂商: {settings.enabled_providers}\n\n"
        "输入 'quit' 退出，输入 'clear' 清空历史",
        title="🚀 CostLens",
    ))

    history: list[dict] = []
    try:
        while True:
            try:
                user_input = console.input("\n[bold green]You>[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if user_input.lower() == "clear":
                history.clear()
                console.print("[yellow]历史已清空[/yellow]")
                continue

            console.print("\n[bold blue]Agent>[/bold blue] ", end="")
            response = ""
            async for token in agent.stream_chat(user_input, history):
                console.print(token, end="", highlight=False)
                response += token

            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})
            console.print()

    finally:
        await agent.close()
        console.print("\n[dim]Goodbye! 👋[/dim]")


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the FastAPI server."""
    import uvicorn
    uvicorn.run(
        "costlens.api.app:app",
        host=host,
        port=port,
        reload=False,
    )


def generate_demo(db_path: str = "costlens_demo.db") -> None:
    """Generate demo dataset."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    from costlens.mock_data import generate_demo_dataset

    console = Console()
    console.print("[bold cyan]Generating demo dataset...[/bold cyan]\n")

    result = generate_demo_dataset(db_path)

    console.print(Panel(
        f"[green]✓[/green] Generated {result['records_generated']} cost records\n"
        f"[green]✓[/green] Generated {result['alerts_generated']} alerts\n"
        f"[green]✓[/green] Generated {result['recommendations_generated']} recommendations\n"
        f"[green]✓[/green] Created {result['budgets_created']} budgets\n\n"
        f"Database: [cyan]{result['db_path']}[/cyan]",
        title="Demo Dataset Generated",
    ))

    # Show stats
    table = Table(title="📊 Storage Stats")
    table.add_column("Table", style="cyan")
    table.add_column("Count", justify="right", style="green")

    for table_name, count in result["stats"].items():
        table.add_row(table_name, str(count))

    console.print(table)


async def run_analysis(days: int) -> None:
    """Run one-shot analysis and print results."""
    from datetime import date, timedelta
    from rich.console import Console
    from rich.table import Table

    from costlens.analysis.analyzer import CostAnalyzer
    from costlens.storage import get_storage

    console = Console()
    analyzer = CostAnalyzer()

    end = date.today()
    start = end - timedelta(days=days)

    console.print(f"\n[bold]Analyzing costs from {start} to {end}...[/bold]\n")

    try:
        result = await analyzer.analyze(start, end)

        # Save to storage
        storage = get_storage()
        storage.save_analysis_run(result)

        console.print(f"[bold cyan]Total Cost:[/bold cyan] {result['total_cost']:.2f}")
        console.print(f"[bold cyan]Alerts:[/bold cyan] {result['alert_count']}")
        console.print(f"[bold cyan]Recommendations:[/bold cyan] {result['recommendation_count']}")
        console.print(
            f"[bold cyan]Potential Savings:[/bold cyan] {result['total_potential_savings']:.2f}"
        )

        if result.get("alerts"):
            table = Table(title="🚨 Alerts")
            table.add_column("Severity")
            table.add_column("Title")
            table.add_column("Message")
            for alert in result["alerts"]:
                if hasattr(alert, "model_dump"):
                    alert = alert.model_dump()
                table.add_row(
                    str(alert.get("severity", "")),
                    str(alert.get("title", "")),
                    str(alert.get("message", ""))[:80],
                )
            console.print(table)

        if result.get("recommendations"):
            table = Table(title="💡 Recommendations")
            table.add_column("Type")
            table.add_column("Title")
            table.add_column("Saving")
            for rec in result["recommendations"][:10]:
                if hasattr(rec, "model_dump"):
                    rec = rec.model_dump()
                table.add_row(
                    str(rec.get("rec_type", "")),
                    str(rec.get("title", ""))[:50],
                    f"{rec.get('estimated_saving', 0):.2f}",
                )
            console.print(table)

        console.print("\n[dim]Analysis saved to database[/dim]")

    finally:
        await analyzer.close()


async def run_report(args) -> None:
    """Generate and display a cost report."""
    from rich.console import Console
    from rich.markdown import Markdown
    from costlens.reports import ReportGenerator

    console = Console()
    generator = ReportGenerator()

    try:
        console.print(f"[bold cyan]Generating {args.type} report...[/bold cyan]\n")

        if args.type == "monthly":
            report = await generator.generate_monthly_report()
        else:
            report = await generator.generate_weekly_report()

        console.print(Markdown(report))
    finally:
        await generator.close()


async def run_balance() -> None:
    """Query account balance from all providers."""
    from rich.console import Console
    from rich.table import Table
    from costlens.config import get_settings
    from costlens.analysis.analyzer import CostAnalyzer

    console = Console()
    settings = get_settings()
    analyzer = CostAnalyzer(settings)

    console.print("[bold cyan]查询账户余额...[/bold cyan]\n")

    table = Table(title="💳 账户余额")
    table.add_column("厂商", style="cyan")
    table.add_column("可用余额", justify="right", style="green")
    table.add_column("信用额度", justify="right", style="yellow")
    table.add_column("货币", style="blue")

    try:
        for provider in settings.get_enabled_providers():
            try:
                connector = await analyzer._get_connector(provider.value)
                balance = await connector.get_account_balance()
                
                if "error" in balance:
                    table.add_row(provider.value, f"错误: {balance['error']}", "", "")
                    continue
                
                available = balance.get("available_amount", 0)
                credit = balance.get("credit_amount", 0)
                currency = balance.get("currency", "CNY")
                
                table.add_row(
                    provider.value,
                    f"{available:,.2f}",
                    f"{credit:,.2f}",
                    currency,
                )
            except Exception as exc:
                table.add_row(provider.value, f"查询失败", "", str(exc))
        
        console.print(table)
    finally:
        await analyzer.close()


async def run_comparison(args) -> None:
    """Generate monthly comparison report."""
    from rich.console import Console
    from rich.markdown import Markdown
    from costlens.analysis.monthly_comparison import MonthlyComparison

    console = Console()
    comparison = MonthlyComparison()

    try:
        console.print("[bold cyan]生成月度对比报告...[/bold cyan]\n")
        
        year = getattr(args, 'year', 0) or None
        month = getattr(args, 'month', 0) or None
        
        report = await comparison.generate_comparison_report(year, month)
        console.print(Markdown(report))
    finally:
        await comparison.close()


async def run_sync() -> None:
    """Run billing data sync."""
    from rich.console import Console
    from costlens.scheduler import BillingScheduler

    console = Console()
    scheduler = BillingScheduler()

    try:
        console.print("[bold cyan]同步账单数据...[/bold cyan]\n")
        result = await scheduler.sync_billing_data()
        
        console.print(f"[green]✓[/green] 同步完成")
        console.print(f"  总记录数: {result['total_records']}")
        console.print(f"  总成本: {result['total_cost']:,.2f} CNY")
        console.print(f"  同步时间: {result['synced_at']}")
        
        for provider, data in result['providers'].items():
            if 'error' in data:
                console.print(f"  [red]✗[/red] {provider}: {data['error']}")
            else:
                console.print(f"  [green]✓[/green] {provider}: {data['records']} records, {data['cost']:,.2f} CNY")
    finally:
        await scheduler._analyzer.close()


def cli_main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="CostLens AI Agent")
    parser.add_argument(
        "command",
        nargs="?",
        default="chat",
        choices=["chat", "server", "analyze", "demo", "wechat-bot", "report", "balance", "compare", "sync"],
        help="Command to run",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--days", type=int, default=30, help="Analysis period in days")
    parser.add_argument("--type", choices=["monthly", "weekly"], default="monthly", help="Report type")
    parser.add_argument("--db", default="costlens.db", help="Database path")

    args = parser.parse_args()
    setup_logging(args.log_level)

    if args.command == "server":
        run_server(args.host, args.port)
    elif args.command == "analyze":
        asyncio.run(run_analysis(args.days))
    elif args.command == "demo":
        generate_demo(args.db)
    elif args.command == "wechat-bot":
        from costlens.wechat_bot import run_wechat_bot
        asyncio.run(run_wechat_bot())
    elif args.command == "report":
        asyncio.run(run_report(args))
    elif args.command == "balance":
        asyncio.run(run_balance())
    elif args.command == "compare":
        asyncio.run(run_comparison(args))
    elif args.command == "sync":
        asyncio.run(run_sync())
    else:
        asyncio.run(interactive_chat())


if __name__ == "__main__":
    cli_main()
