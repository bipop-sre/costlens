"""Alert notification system for DingTalk, Feishu, and WeChat Work."""

from __future__ import annotations

import abc
import hashlib
import hmac
import json
import logging
import time
from base64 import b64encode
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

from costlens.models.alert import Alert, AlertSeverity

logger = logging.getLogger(__name__)


class Notifier(abc.ABC):
    """Abstract base class for notification providers."""

    @abc.abstractmethod
    async def send(self, alert: Alert) -> bool:
        """Send an alert notification. Returns True if successful."""

    @abc.abstractmethod
    async def send_batch(self, alerts: list[Alert]) -> int:
        """Send multiple alerts. Returns count of successful sends."""


class DingTalkNotifier(Notifier):
    """DingTalk (钉钉) webhook notifier."""

    def __init__(self, webhook_url: str, secret: Optional[str] = None) -> None:
        self.webhook_url = webhook_url
        self.secret = secret

    def _sign_url(self) -> str:
        """Add timestamp and signature to webhook URL."""
        if not self.secret:
            return self.webhook_url

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = quote_plus(b64encode(hmac_code))
        return f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"

    def _format_alert(self, alert: Alert) -> dict:
        """Format alert as DingTalk markdown message."""
        severity_emoji = {
            AlertSeverity.CRITICAL: "🔴",
            AlertSeverity.WARNING: "🟡",
            AlertSeverity.INFO: "🔵",
        }
        emoji = severity_emoji.get(alert.severity, "⚪")

        markdown_text = (
            f"### {emoji} {alert.title}\n\n"
            f"**{alert.message}**\n\n"
            f"- 云厂商: {alert.provider}\n"
            f"- 严重程度: {alert.severity.value}\n"
            f"- 当前值: {alert.current_value:.2f} {alert.currency}\n"
            f"- 阈值: {alert.threshold_value:.2f} {alert.currency}\n"
            f"- 时间: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        return {
            "msgtype": "markdown",
            "markdown": {
                "title": alert.title,
                "text": markdown_text,
            },
        }

    async def send(self, alert: Alert) -> bool:
        url = self._sign_url()
        payload = self._format_alert(alert)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                data = response.json()
                if data.get("errcode") == 0:
                    logger.info("DingTalk notification sent: %s", alert.title)
                    return True
                else:
                    logger.error("DingTalk error: %s", data)
                    return False
        except Exception as e:
            logger.error("DingTalk notification failed: %s", e)
            return False

    async def send_batch(self, alerts: list[Alert]) -> int:
        if not alerts:
            return 0

        # Combine multiple alerts into one message
        severity_emoji = {
            AlertSeverity.CRITICAL: "🔴",
            AlertSeverity.WARNING: "🟡",
            AlertSeverity.INFO: "🔵",
        }

        lines = [f"## 📊 CostLens 告警汇总 ({len(alerts)} 条)\n"]
        for alert in alerts[:10]:  # Limit to 10 alerts
            emoji = severity_emoji.get(alert.severity, "⚪")
            lines.append(f"{emoji} **{alert.title}**")
            lines.append(f"  - {alert.message}")
            lines.append(f"  - 当前: {alert.current_value:.2f} / 阈值: {alert.threshold_value:.2f}\n")

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"CostLens 告警汇总 ({len(alerts)} 条)",
                "text": "\n".join(lines),
            },
        }

        try:
            url = self._sign_url()
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                data = response.json()
                if data.get("errcode") == 0:
                    return len(alerts)
                return 0
        except Exception as e:
            logger.error("DingTalk batch notification failed: %s", e)
            return 0


class FeishuNotifier(Notifier):
    """Feishu (飞书/Lark) webhook notifier."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def _format_alert(self, alert: Alert) -> dict:
        """Format alert as Feishu interactive card message."""
        severity_color = {
            AlertSeverity.CRITICAL: "red",
            AlertSeverity.WARNING: "yellow",
            AlertSeverity.INFO: "blue",
        }
        color = severity_color.get(alert.severity, "grey")

        severity_emoji = {
            AlertSeverity.CRITICAL: "🔴",
            AlertSeverity.WARNING: "🟡",
            AlertSeverity.INFO: "🔵",
        }
        emoji = severity_emoji.get(alert.severity, "⚪")

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{emoji} {alert.title}",
                },
                "template": color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{alert.message}**",
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**云厂商:**\n{alert.provider}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**严重程度:**\n{alert.severity.value}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**当前值:**\n{alert.current_value:.2f} {alert.currency}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**阈值:**\n{alert.threshold_value:.2f} {alert.currency}"}},
                    ],
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"⏰ {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
                        }
                    ],
                },
            ],
        }

        return {"msg_type": "interactive", "card": card}

    async def send(self, alert: Alert) -> bool:
        payload = self._format_alert(alert)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=payload, timeout=10.0)
                data = response.json()
                if data.get("code") == 0 or data.get("StatusCode") == 0:
                    logger.info("Feishu notification sent: %s", alert.title)
                    return True
                else:
                    logger.error("Feishu error: %s", data)
                    return False
        except Exception as e:
            logger.error("Feishu notification failed: %s", e)
            return False

    async def send_batch(self, alerts: list[Alert]) -> int:
        success_count = 0
        for alert in alerts:
            if await self.send(alert):
                success_count += 1
        return success_count


class WeChatWorkBotNotifier(Notifier):
    """WeChat Work intelligent bot (智能机器人) via WebSocket long connection.

    When a ``WeChatBotService`` is attached via ``set_bot_service``, incoming
    messages are routed to the CostLens AI Agent for intelligent conversation.
    Without a bot service, the notifier falls back to static help/welcome
    replies and alert-only push notifications.
    """

    def __init__(self, bot_id: str, secret: str) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self._client = None
        self._connected_chatids: set[str] = set()
        self._ws_connected = False
        self._bot_service = None  # Optional WeChatBotService

    def set_bot_service(self, service) -> None:
        """Attach a WeChatBotService for AI-powered message handling."""
        self._bot_service = service

    async def _ensure_connected(self):
        if self._client is None:
            from wecom_aibot_sdk import WSClient
            self._client = WSClient(
                self.bot_id,
                self.secret,
                max_reconnect_attempts=5,
                reconnect_interval=2000,
            )

            async def handle_text(frame):
                await self._on_message(frame)

            async def handle_enter(frame):
                body = frame.get("body") or {}
                from_info = body.get("from") or {}
                userid = from_info.get("userid", "") if isinstance(from_info, dict) else ""
                chatid = body.get("chatid") or userid
                if chatid:
                    self._connected_chatids.add(chatid)

            self._client.on("message.text", handle_text)
            self._client.on("event.enter_chat", handle_enter)

        if not self._ws_connected:
            await self._client.connect()
            self._ws_connected = True

    async def _on_message(self, frame) -> None:
        body = frame.get("body") or {}
        from_info = body.get("from") or {}
        userid = from_info.get("userid", "") if isinstance(from_info, dict) else ""
        chatid = body.get("chatid") or userid
        if chatid:
            self._connected_chatids.add(chatid)

        msgtype = body.get("msgtype", "")
        if msgtype == "text":
            text_info = body.get("text") or {}
            content = text_info.get("content", "").strip() if isinstance(text_info, dict) else ""
        else:
            content = ""
        logger.info("WeChat Work bot message from %s: %s", chatid, content)

        # Delegate to WeChatBotService for AI-powered conversation
        if self._bot_service is not None:
            try:
                await self._bot_service._handle_message(frame)
                return
            except Exception as exc:
                logger.error("Bot service failed, using fallback: %s", exc)

        # Fallback: static replies when no bot service is attached
        if content.strip() in ["帮助", "help", "?", "？"]:
            reply_text = (
                "## CostLens 成本监控助手\n\n"
                "发送以下指令获取信息：\n"
                "- **成本** / **cost** - 查看云成本概览\n"
                "- **告警** / **alert** - 查看当前告警\n"
                "- **服务** / **service** - 查看服务费用分布\n"
                "- **帮助** / **help** - 显示此帮助\n"
            )
        else:
            reply_text = (
                "## 👋 CostLens AI Agent 已就绪\n\n"
                "已连接并准备为您提供多云成本监控服务。\n\n"
                "发送 **帮助** 查看可用指令。"
            )

        try:
            await self._client.reply(
                frame.headers,
                {"msgtype": "markdown", "markdown": {"content": reply_text}},
                "aibot_respond_msg",
            )
        except Exception as exc:
            logger.error("Failed to reply: %s", exc)

    async def send(self, alert: Alert) -> bool:
        try:
            await self._ensure_connected()
        except Exception as exc:
            logger.error("WebSocket not connected: %s", exc)
            return False

        severity_emoji = {
            AlertSeverity.CRITICAL: "🔴",
            AlertSeverity.WARNING: "🟡",
            AlertSeverity.INFO: "🔵",
        }
        emoji = severity_emoji.get(alert.severity, "⚪")
        content = (
            f"## {emoji} {alert.title}\n\n"
            f"**{alert.message}**\n\n"
            f"- 云厂商: <font color=\"info\">{alert.provider}</font>\n"
            f"- 严重程度: {alert.severity.value}\n"
            f"- 当前值: <font color=\"warning\">{alert.current_value:.2f} {alert.currency}</font>\n"
            f"- 阈值: {alert.threshold_value:.2f} {alert.currency}\n"
            f"- 时间: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        success_count = 0
        for chatid in self._connected_chatids:
            try:
                await self._client.send_message(
                    chatid,
                    {"msgtype": "markdown", "markdown": {"content": content}},
                )
                success_count += 1
            except Exception as exc:
                logger.error("Failed to send to %s: %s", chatid, exc)
        return success_count > 0

    async def send_batch(self, alerts: list[Alert]) -> int:
        if not alerts:
            return 0
        try:
            await self._ensure_connected()
        except Exception:
            return 0

        severity_emoji = {AlertSeverity.CRITICAL: "🔴", AlertSeverity.WARNING: "🟡", AlertSeverity.INFO: "🔵"}
        lines = [f"## 📊 CostLens 告警汇总 ({len(alerts)} 条)\n"]
        for alert in alerts[:10]:
            emoji = severity_emoji.get(alert.severity, "⚪")
            lines.append(f"{emoji} **{alert.title}**")
            lines.append(f"  > {alert.message}")
            lines.append(f"  当前: {alert.current_value:.2f} / 阈值: {alert.threshold_value:.2f}\n")
        content = "\n".join(lines)

        success_count = 0
        for chatid in self._connected_chatids:
            try:
                await self._client.send_message(
                    chatid,
                    {"msgtype": "markdown", "markdown": {"content": content}},
                )
                success_count += 1
            except Exception as exc:
                logger.error("Failed to send batch to %s: %s", chatid, exc)
        return success_count

    async def send_proactive(self, chatid: str, content: str) -> bool:
        try:
            await self._ensure_connected()
            await self._client.send_message(
                chatid,
                {"msgtype": "markdown", "markdown": {"content": content}},
            )
            return True
        except Exception as exc:
            logger.error("Failed to send proactive message: %s", exc)
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
                self._ws_connected = False
            except Exception as exc:
                logger.warning("Error disconnecting: %s", exc)


class NotificationManager:
    """Manages multiple notification providers."""

    def __init__(self) -> None:
        self._notifiers: list[Notifier] = []

    def add_notifier(self, notifier: Notifier) -> None:
        self._notifiers.append(notifier)

    def add_dingtalk(self, webhook_url: str, secret: Optional[str] = None) -> None:
        self.add_notifier(DingTalkNotifier(webhook_url, secret))

    def add_feishu(self, webhook_url: str) -> None:
        self.add_notifier(FeishuNotifier(webhook_url))


    def add_wechat_work_bot(self, bot_id: str, secret: str) -> None:
        self.add_notifier(WeChatWorkBotNotifier(bot_id, secret))

    async def notify(self, alert: Alert) -> dict[str, bool]:
        """Send alert to all configured notifiers."""
        results = {}
        for i, notifier in enumerate(self._notifiers):
            notifier_name = type(notifier).__name__
            results[notifier_name] = await notifier.send(alert)
        return results

    async def notify_batch(self, alerts: list[Alert]) -> dict[str, int]:
        """Send batch of alerts to all configured notifiers."""
        results = {}
        for notifier in self._notifiers:
            notifier_name = type(notifier).__name__
            results[notifier_name] = await notifier.send_batch(alerts)
        return results

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> NotificationManager:
        """Create notification manager from config dict."""
        manager = cls()

        if "dingtalk" in config:
            dt = config["dingtalk"]
            manager.add_dingtalk(dt["webhook_url"], dt.get("secret"))

        if "feishu" in config:
            fs = config["feishu"]
            manager.add_feishu(fs["webhook_url"])

        return manager


# Global notification manager
_notification_manager: NotificationManager | None = None


def get_notification_manager() -> NotificationManager:
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager()
    return _notification_manager
