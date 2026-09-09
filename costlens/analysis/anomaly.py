"""Cost anomaly detection."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

import numpy as np

from costlens.models.alert import Alert, AlertSeverity, AlertType
from costlens.models.cost import CostRecord

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detect cost anomalies using statistical methods."""

    def __init__(self, threshold_sigma: float = 2.0, spike_threshold_pct: float = 30.0) -> None:
        self.threshold_sigma = threshold_sigma
        self.spike_threshold_pct = spike_threshold_pct

    def detect_anomalies(
        self,
        records: list[CostRecord],
        provider: str = "unknown",
    ) -> list[Alert]:
        """Detect cost anomalies using z-score method per service."""
        service_daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in records:
            service_daily[r.service_name][r.date.isoformat()] += r.cost

        alerts = []
        for service, daily in service_daily.items():
            sorted_dates = sorted(daily.keys())
            if len(sorted_dates) < 7:
                continue

            values = np.array([daily[d] for d in sorted_dates])
            mean = float(np.mean(values[:-1]))
            std = float(np.std(values[:-1]))
            latest_cost = float(values[-1])
            latest_date = sorted_dates[-1]

            if std > 0:
                z_score = (latest_cost - mean) / std
                if abs(z_score) >= self.threshold_sigma:
                    severity = AlertSeverity.CRITICAL if abs(z_score) >= 3 else AlertSeverity.WARNING
                    pct_change = ((latest_cost - mean) / mean * 100) if mean > 0 else 0
                    direction = "上升" if z_score > 0 else "下降"
                    alerts.append(Alert(
                        alert_type=AlertType.COST_ANOMALY,
                        severity=severity,
                        title=f"{service} 成本异常{direction}",
                        message=(
                            f"{service} 在 {latest_date} 的成本为 {latest_cost:.2f}，"
                            f"较历史均值 {mean:.2f} {direction}了 {abs(pct_change):.1f}%"
                            f"（z-score: {z_score:.2f}）"
                        ),
                        provider=provider,
                        current_value=latest_cost,
                        threshold_value=mean + self.threshold_sigma * std,
                    ))

            if len(values) >= 2:
                prev_cost = float(values[-2])
                if prev_cost > 0:
                    change_pct = (latest_cost - prev_cost) / prev_cost * 100
                    if change_pct >= self.spike_threshold_pct:
                        alerts.append(Alert(
                            alert_type=AlertType.COST_SPIKE,
                            severity=AlertSeverity.CRITICAL if change_pct >= 50 else AlertSeverity.WARNING,
                            title=f"{service} 成本骤增",
                            message=(
                                f"{service} 日环比增长 {change_pct:.1f}%，"
                                f"从 {prev_cost:.2f} 增至 {latest_cost:.2f}"
                            ),
                            provider=provider,
                            current_value=latest_cost,
                            threshold_value=prev_cost * (1 + self.spike_threshold_pct / 100),
                        ))

        return alerts

    def detect_new_services(
        self,
        records: list[CostRecord],
        known_services: set[str] | None = None,
    ) -> list[Alert]:
        """Detect newly appearing services that may indicate unexpected usage."""
        if known_services is None:
            known_services = set()

        current_services = {r.service_name for r in records}
        new_services = current_services - known_services
        alerts = []

        for service in new_services:
            service_cost = sum(r.cost for r in records if r.service_name == service)
            if service_cost > 0:
                alerts.append(Alert(
                    alert_type=AlertType.COST_ANOMALY,
                    severity=AlertSeverity.INFO,
                    title=f"新服务出现: {service}",
                    message=f"发现新的成本服务 {service}，总成本 {service_cost:.2f}",
                    provider=records[0].provider if records else "unknown",
                    current_value=service_cost,
                ))

        return alerts
