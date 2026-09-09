"""Tests for notification system."""

import pytest
from datetime import datetime

from costlens.models.alert import Alert, AlertSeverity, AlertType
from costlens.notifications import (
    DingTalkNotifier,
    FeishuNotifier,
    NotificationManager,
)


@pytest.fixture
def sample_alert():
    return Alert(
        alert_type=AlertType.COST_ANOMALY,
        severity=AlertSeverity.WARNING,
        title="EC2 Cost Spike",
        message="EC2 cost increased by 50% in the last 24 hours",
        provider="aws",
        current_value=1500.0,
        threshold_value=1000.0,
        currency="USD",
        timestamp=datetime(2024, 1, 15, 10, 30, 0),
    )


class TestDingTalkNotifier:
    def test_format_alert(self, sample_alert):
        notifier = DingTalkNotifier("https://example.com/webhook")
        payload = notifier._format_alert(sample_alert)
        assert payload["msgtype"] == "markdown"
        assert "EC2 Cost Spike" in payload["markdown"]["title"]
        assert "aws" in payload["markdown"]["text"]

    def test_sign_url_without_secret(self):
        notifier = DingTalkNotifier("https://example.com/webhook")
        url = notifier._sign_url()
        assert url == "https://example.com/webhook"

    def test_sign_url_with_secret(self):
        notifier = DingTalkNotifier("https://example.com/webhook", secret="test-secret")
        url = notifier._sign_url()
        assert "timestamp=" in url
        assert "sign=" in url


class TestFeishuNotifier:
    def test_format_alert(self, sample_alert):
        notifier = FeishuNotifier("https://example.com/webhook")
        payload = notifier._format_alert(sample_alert)
        assert payload["msg_type"] == "interactive"
        assert "card" in payload
        assert payload["card"]["header"]["title"]["content"] == "🟡 EC2 Cost Spike"


class TestNotificationManager:
    def test_add_notifiers(self):
        manager = NotificationManager()
        manager.add_dingtalk("https://example.com/dingtalk")
        manager.add_feishu("https://example.com/feishu")
        assert len(manager._notifiers) == 2

    def test_from_config(self):
        config = {
            "dingtalk": {"webhook_url": "https://example.com/dingtalk", "secret": "test"},
            "feishu": {"webhook_url": "https://example.com/feishu"},
        }
        manager = NotificationManager.from_config(config)
        assert len(manager._notifiers) == 2

    @pytest.mark.asyncio
    async def test_notify_with_invalid_url(self, sample_alert):
        manager = NotificationManager()
        manager.add_dingtalk("https://invalid-url-that-will-fail.com/webhook")
        results = await manager.notify(sample_alert)
        assert "DingTalkNotifier" in results
        assert results["DingTalkNotifier"] is False
