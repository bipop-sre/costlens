"""Hourly billing data sync scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from costlens.analysis.analyzer import CostAnalyzer
from costlens.config import Settings, get_settings
from costlens.models.cost import CostRecord, Granularity
from costlens.storage import get_storage
from costlens.analysis.proactive_inspector import ProactiveInspector

logger = logging.getLogger(__name__)


class BillingScheduler:
    """Scheduled billing data synchronization."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._analyzer = CostAnalyzer(self.settings)
        self._storage = get_storage()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_sync: Optional[datetime] = None
        self._inspector = ProactiveInspector(settings)
        self._broadcast_fn = None

    def set_broadcast_fn(self, broadcast_fn):
        """Set the broadcast function for notifications."""
        self._broadcast_fn = broadcast_fn

    async def sync_billing_data(self) -> dict:
        """Sync billing data from all enabled cloud providers (monthly + daily)."""
        logger.info("Starting billing data sync...")
        end = date.today()
        start = end - timedelta(days=30)

        results = {}
        total_records = 0
        total_cost = 0.0

        for provider in self.settings.get_enabled_providers():
            try:
                connector = await self._analyzer._get_connector(provider.value)

                # ── Monthly data (all months including current) ──
                records = await connector.get_cost_data(start, end)
                count = self._storage.save_cost_records(records)
                cost = sum(r.cost for r in records)

                provider_result = {
                    "monthly_records": len(records),
                    "monthly_cost": cost,
                }
                total_records += len(records)
                total_cost += cost
                logger.info("%s: monthly %d records, %.2f CNY", provider.value, len(records), cost)

                # ── Daily granularity for current month ──
                try:
                    daily_records = await self._fetch_daily_data(connector, provider.value, end)
                    if daily_records:
                        self._storage.save_cost_records(daily_records)
                        daily_cost = sum(r.cost for r in daily_records)
                        provider_result["daily_records"] = len(daily_records)
                        provider_result["daily_cost"] = daily_cost
                        total_records += len(daily_records)
                        total_cost += daily_cost
                        logger.info("%s: daily %d records, %.2f CNY", provider.value, len(daily_records), daily_cost)
                except Exception as exc:
                    logger.warning("Daily sync for %s failed: %s", provider.value, exc)

                # ── Balance ──
                try:
                    balance = await connector.get_account_balance()
                    if balance and "error" not in balance:
                        self._storage.save_balance_record(provider.value, balance)
                        logger.info("%s balance: %.2f CNY", provider.value, balance.get("available_amount", 0))
                except Exception as exc:
                    logger.warning("Balance for %s failed: %s", provider.value, exc)

                results[provider.value] = provider_result

            except Exception as exc:
                logger.error("Failed to sync %s: %s", provider.value, exc)
                results[provider.value] = {"error": str(exc)}

        self._last_sync = datetime.now()
        result = {
            "total_records": total_records,
            "total_cost": total_cost,
            "providers": results,
            "synced_at": self._last_sync.isoformat(),
        }
        logger.info("Billing sync done: %d records, %.2f total", total_records, total_cost)
        
        # Run proactive inspection after sync
        if self._broadcast_fn:
            try:
                inspection_results = await self._inspector.inspect_after_sync(self._broadcast_fn)
                result["inspection"] = inspection_results
                logger.info("Inspection done: %s", inspection_results)
            except Exception as exc:
                logger.error("Inspection failed: %s", exc)
        
        # Check budget thresholds
        try:
            from costlens.web.budget_routes import check_budgets
            budget_result = await check_budgets()
            result["budget_check"] = budget_result
            logger.info("Budget check done: %s", budget_result)
        except Exception as exc:
            logger.error("Budget check failed: %s", exc)
        
        return result

    async def _fetch_daily_data(self, connector, provider_name: str, today: date) -> list[CostRecord]:
        """Fetch daily granularity data for the current month up to today."""
        from collections import defaultdict
        
        year = today.year
        month = today.month
        day = today.day

        if provider_name == "alibaba":
            client = connector._get_client()
            month_str = f"{year}-{month:02d}"
            start_date = date(year, month, 1)
            end_date = today

            all_items, account_id = connector._fetch_daily_items_for_month(
                client, month_str, start_date, end_date
            )

            # Aggregate by unique key to prevent data loss
            aggregated = defaultdict(lambda: {"cost": 0.0, "currency": "CNY", "tags": {}})
            
            for item in all_items:
                cost = float(item.pretax_amount or 0)
                if not item.billing_date:
                    continue
                try:
                    record_date = date.fromisoformat(item.billing_date)
                except ValueError:
                    continue
                
                service = item.product_name or item.product_code or "Unknown"
                sub_type = getattr(item, 'subscription_type', '') or ''
                key = (service, record_date, sub_type)
                
                aggregated[key]["cost"] += cost
                aggregated[key]["currency"] = item.currency or "CNY"
                aggregated[key]["tags"] = {
                    "product_code": item.product_code or "",
                    "subscription_type": sub_type,
                    "biz_type": getattr(item, 'biz_type', '') or "",
                }
            
            # Create aggregated records
            records = []
            for (service, record_date, sub_type), data in aggregated.items():
                records.append(CostRecord(
                    provider=provider_name,
                    account_id=account_id or connector._account_id or "default",
                    service_name=service,
                    region="",
                    cost=data["cost"],
                    currency=data["currency"],
                    date=record_date,
                    granularity=Granularity.DAILY,
                    tags=data["tags"],
                ))
            return records

        elif provider_name == "tencent":
            return await connector.get_daily_cost_data(year, month, 1, day)

        return []

    async def start(self, interval_hours: int = 1, initial_sync: bool = True) -> None:
        """Start the scheduler with periodic sync.
        
        Args:
            interval_hours: Sync interval in hours.
            initial_sync: If True, run initial sync in background (non-blocking).
        """
        if self._running:
            return

        self._running = True
        interval_seconds = interval_hours * 3600
        logger.info("Starting billing scheduler (interval: %dh)", interval_hours)

        async def do_sync():
            try:
                await self.sync_billing_data()
            except Exception as exc:
                logger.error("Sync failed: %s", exc)

        if initial_sync:
            asyncio.create_task(do_sync())

        async def sync_loop():
            while self._running:
                await asyncio.sleep(interval_seconds)
                await do_sync()

        self._task = asyncio.create_task(sync_loop())

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._analyzer.close()

    @property
    def last_sync(self) -> Optional[datetime]:
        return self._last_sync

    @property
    def is_running(self) -> bool:
        return self._running
