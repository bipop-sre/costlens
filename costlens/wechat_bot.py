"""WeChat Work intelligent bot service with CostLens AI Agent integration.

Provides a WebSocket-based bot that connects to WeChat Work (企业微信) intelligent
bot platform, receives user messages, and responds with CostLens AI Agent's analysis
using streaming replies for real-time feedback.
"""

from __future__ import annotations

import logging
from typing import Optional

from costlens.agent.chat import ChatSession
from costlens.agent.core import CostLensAgent
from costlens.scheduler import BillingScheduler
from costlens.config import Settings, get_settings

logger = logging.getLogger(__name__)


HELP_TEXT = (
    "## 📊 CostLens 成本监控助手\n\n"
    "我是您的多云成本管理 AI 助手，可以帮您：\n\n"
    "- 查询各云厂商成本概览\n"
    "- 分析成本趋势和异常\n"
    "- 提供优化建议和预算监控\n"
    "- 回答任何云财务管理问题\n\n"
    "**常用指令：**\n"
    "- `这个月花了多少钱` — 成本概览\n"
    "- `有什么异常吗` — 异常检测\n"
    "- `有什么优化建议` — 优化建议\n"
    "- `帮我看看预算` — 预算检查\n"
    "- `/clear` — 清空对话历史\n"
    "- `/help` — 显示此帮助\n\n"
    "💡 您也可以直接用自然语言提问，我会尽力回答。"
)


class WeChatBotService:
    """WeChat Work intelligent bot service backed by CostLens AI Agent.

    Manages WebSocket connection lifecycle, per-chat conversation sessions,
    and message routing with streaming reply support.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._agent: Optional[CostLensAgent] = None
        self._ws_client = None
        self._sessions: dict[str, ChatSession] = {}
        self._connected_chatids: set[str] = set()
        self._running = False
        self._scheduler: Optional[BillingScheduler] = None

    async def start(self) -> None:
        """Initialize agent and WebSocket client, then connect."""
        from wecom_aibot_sdk import WSClient

        if self._running:
            return

        bot_id = self.settings.wechat_work_bot_id
        bot_secret = self.settings.wechat_work_bot_secret
        if not bot_id or not bot_secret:
            raise ValueError(
                "WECHAT_WORK_BOT_ID and WECHAT_WORK_BOT_SECRET must be configured"
            )

        self._agent = CostLensAgent(self.settings)

        self._ws_client = WSClient(
            bot_id,
            bot_secret,
            max_reconnect_attempts=-1,  # infinite reconnection
            reconnect_interval=3000,
        )

        self._ws_client.on("message.text", self._handle_message)
        self._ws_client.on("event.enter_chat", self._handle_enter)

        await self._ws_client.connect()
        self._running = True
        
        # Auto-load configured target chatids so reports work without manual reconnection
        if self.settings.report_target_chatids:
            for chatid in self.settings.report_target_chatids.split(','):
                chatid = chatid.strip()
                if chatid:
                    self._connected_chatids.add(chatid)
            logger.info("Pre-loaded %d target chatid(s) from config: %s", 
                       len(self._connected_chatids), self._connected_chatids)
        
        # Start billing scheduler (hourly sync)
        self._scheduler = BillingScheduler(self.settings)
        self._scheduler.set_broadcast_fn(self.broadcast)
        await self._scheduler.start(interval_hours=1)
        
        logger.info("WeChat Bot Service started, bot_id=%s...", bot_id[:12])

    async def stop(self) -> None:
        """Disconnect WebSocket and clean up agent resources."""
        self._running = False
        if self._ws_client is not None:
            try:
                await self._ws_client.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting WebSocket: %s", exc)
        if self._scheduler is not None:
            await self._scheduler.stop()
        if self._agent is not None:
            await self._agent.close()
        self._sessions.clear()
        self._connected_chatids.clear()
        logger.info("WeChat Bot Service stopped")

    def get_session(self, chatid: str) -> ChatSession:
        """Get or create a chat session for the given chatid."""
        if chatid not in self._sessions:
            self._sessions[chatid] = ChatSession(
                session_id=chatid,
                agent=self._agent,
            )
            logger.info("Created session for chatid: %s", chatid)
        return self._sessions[chatid]

    async def _handle_enter(self, frame) -> None:
        """Handle user entering a chat session."""
        body = frame.get("body") or {}
        from_info = body.get("from") or {}
        userid = from_info.get("userid", "") if isinstance(from_info, dict) else ""
        chatid = body.get("chatid") or userid
        if chatid:
            self._connected_chatids.add(chatid)
            logger.info("User entered chat: %s", chatid)

    async def _handle_message(self, frame) -> None:
        """Route incoming message to command handler or AI agent."""
        body = frame.get("body")
        if not isinstance(body, dict):
            return

        # Parse message structure from WeChat Bot SDK
        # Text: body["text"]["content"], userid: body["from"]["userid"]
        msgtype = body.get("msgtype", "")
        from_info = body.get("from") or {}
        userid = from_info.get("userid", "") if isinstance(from_info, dict) else ""

        if msgtype == "text":
            text_info = body.get("text") or {}
            content = text_info.get("content", "").strip() if isinstance(text_info, dict) else ""
        else:
            # For now, only handle text messages
            logger.info("Ignoring non-text message type: %s", msgtype)
            return

        # Use userid as session key for single chats
        # For group chats, chattype is "group" and chatid may be present
        chattype = body.get("chattype", "single")
        chatid = body.get("chatid") or userid

        if chatid:
            self._connected_chatids.add(chatid)

        logger.info(
            "Message from %s (%s, chattype=%s): %s",
            userid or "unknown",
            chatid[:20],
            chattype,
            content[:100],
        )

        if not content:
            return

        if content in ("/help", "帮助", "help"):
            await self._reply_markdown(frame, HELP_TEXT)
            return

        if content in ("/clear", "清空", "clear"):
            session = self._sessions.get(chatid)
            if session:
                session.clear_history()
            await self._reply_markdown(frame, "✅ 对话历史已清空，可以开始新的对话。")
            return

        if content in ("/monthly", "月报", "本月月报"):
            await self._handle_report(frame, "monthly")
            return

        if content in ("/weekly", "周报", "本周周报"):
            await self._handle_report(frame, "weekly")
            return

        if content in ("/balance", "余额", "账户余额"):
            await self._handle_balance(frame)
            return

        if content in ("/compare", "同比", "环比", "月度对比"):
            await self._handle_monthly_comparison(frame)
            return

        await self._handle_ai_chat(frame, chatid, content)

    async def _handle_report(self, frame, report_type: str) -> None:
        """Generate and send a cost report."""
        from costlens.reports import ReportGenerator

        try:
            generator = ReportGenerator(self.settings)
            if report_type == "monthly":
                logger.info("Generating monthly report...")
                report = await generator.generate_monthly_report()
            else:
                logger.info("Generating weekly report...")
                report = await generator.generate_weekly_report()
            await generator.close()

            logger.info("Report generated (%d chars), sending...", len(report))
            await self._reply_markdown(frame, report)
            logger.info("Report sent successfully")

        except Exception as exc:
            logger.error("Report generation failed: %s", exc, exc_info=True)
            error_text = (
                "## ⚠️ 报告生成失败\n\n"
                f"生成{report_type}报告时遇到问题: {exc}"
            )
            try:
                await self._reply_markdown(frame, error_text)
            except Exception:
                pass

    async def _handle_balance(self, frame) -> None:
        """Query and send account balance."""
        try:
            balances = []
            total_available = 0.0
            total_credit = 0.0
            
            for provider in self.settings.get_enabled_providers():
                try:
                    connector = await self._agent.analyzer._get_connector(provider.value)
                    balance = await connector.get_account_balance()
                    
                    if "error" in balance:
                        continue
                    
                    available = balance.get("available_amount", 0)
                    credit = balance.get("credit_amount", 0)
                    currency = balance.get("currency", "CNY")
                    
                    provider_name = {"alibaba": "阿里云", "tencent": "腾讯云"}.get(provider.value, provider.value)
                    balances.append(f"- **{provider_name}**: 可用 {available:,.2f} {currency} | 信用额度 {credit:,.2f} {currency}")
                    total_available += available
                    total_credit += credit
                except Exception as exc:
                    logger.error("Balance query failed for %s: %s", provider.value, exc)
            
            if balances:
                report = "## 💳 账户余额\n\n"
                report += "\n".join(balances)
                report += f"\n\n**合计**: 可用 {total_available:,.2f} CNY | 信用额度 {total_credit:,.2f} CNY"
                await self._reply_markdown(frame, report)
            else:
                await self._reply_markdown(frame, "⚠️ 无法获取余额信息")
                
        except Exception as exc:
            logger.error("Balance handler failed: %s", exc, exc_info=True)
            await self._reply_markdown(frame, f"⚠️ 查询余额失败: {exc}")

    async def _handle_monthly_comparison(self, frame) -> None:
        """Generate and send monthly comparison report."""
        from costlens.analysis.monthly_comparison import MonthlyComparison
        
        try:
            logger.info("Generating monthly comparison report...")
            comparison = MonthlyComparison(self.settings)
            report = await comparison.generate_comparison_report()
            await comparison.close()
            
            logger.info("Comparison report generated (%d chars)", len(report))
            await self._reply_markdown(frame, report)
            
        except Exception as exc:
            logger.error("Monthly comparison failed: %s", exc, exc_info=True)
            error_text = f"## ⚠️ 生成对比报告失败\n\n错误: {exc}"
            try:
                await self._reply_markdown(frame, error_text)
            except Exception:
                pass

    async def _handle_ai_chat(self, frame, chatid: str, content: str) -> None:
        """Process message through CostLens AI Agent."""
        session = self.get_session(chatid)

        try:
            logger.info("Calling AI agent for: %s", content[:50])
            full_response = await self._agent.chat(content, session.get_history())
            logger.info("AI response (%d chars): %s", len(full_response), full_response[:100])

            session.history.append({"role": "user", "content": content})
            session.history.append({"role": "assistant", "content": full_response})
            if len(session.history) > session.max_history:
                session.history = session.history[-session.max_history :]

            await self._reply_markdown(frame, full_response)

        except Exception as exc:
            logger.error("AI chat failed for chatid=%s: %s", chatid, exc, exc_info=True)
            error_text = (
                "## ⚠️ 处理失败\n\n"
                "抱歉，处理您的请求时遇到了问题，请稍后重试。\n\n"
                f"错误信息: {exc}"
            )
            try:
                await self._reply_markdown(frame, error_text)
            except Exception:
                pass

    async def _reply_markdown(self, frame, content: str) -> None:
        """Send a complete markdown reply (non-streaming)."""
        logger.info("Sending markdown reply: %s", content[:50])
        try:
            result = await self._ws_client.reply(
                frame,
                {"msgtype": "markdown", "markdown": {"content": content}},
                "aibot_respond_msg",
            )
            logger.info("Markdown reply sent successfully")
        except Exception as exc:
            logger.error("Markdown reply failed: %s", exc, exc_info=True)

    async def broadcast(self, content: str, target_chatids: Optional[set[str]] = None) -> int:
        """Send a message to chats. If target_chatids is provided, only send to those; otherwise send to all.
        
        Args:
            content: Markdown content to send
            target_chatids: Optional set of chatids to send to. If None, broadcasts to all connected chats.
            
        Returns:
            Count of successful sends
        """
        if not self._running or self._ws_client is None:
            return 0

        # Determine which chatids to send to
        if target_chatids is not None:
            # Filter to only connected targets
            send_to = target_chatids & self._connected_chatids
            if not send_to:
                logger.warning("No matching connected chatids for targets: %s", target_chatids)
                return 0
        else:
            send_to = self._connected_chatids

        success = 0
        for chatid in send_to:
            try:
                await self._ws_client.send_message(
                    chatid,
                    {"msgtype": "markdown", "markdown": {"content": content}},
                )
                success += 1
            except Exception as exc:
                logger.error("Broadcast to %s failed: %s", chatid, exc)
        return success

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connected_chatids(self) -> set[str]:
        return self._connected_chatids.copy()

    @property
    def session_count(self) -> int:
        return len(self._sessions)


async def run_wechat_bot(settings: Optional[Settings] = None) -> None:
    """Run the WeChat Bot service as a long-running process.

    This is the main entry point for ``costlens wechat-bot`` CLI command.
    Auto-restarts on unexpected WebSocket disconnection.
    """
    import asyncio
    import signal

    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    stop_event = asyncio.Event()

    def _signal_handler():
        console.print("\n[yellow]Received shutdown signal...[/yellow]")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    restart_delay = 5
    while not stop_event.is_set():
        service = WeChatBotService(settings)
        try:
            await service.start()
            settings_obj = service.settings
            console.print(Panel(
                f"[bold green]✅ WeChat Bot Service 已启动[/bold green]\n\n"
                f"模型: {settings_obj.openai_model}\n"
                f"云厂商: {settings_obj.enabled_providers}\n"
                f"Bot ID: {settings_obj.wechat_work_bot_id[:12]}...\n\n"
                f"[dim]按 Ctrl+C 停止服务[/dim]",
                title="🤖 CostLens WeChat Bot",
            ))

            await stop_event.wait()
        except Exception as exc:
            logger.error("WeChat Bot Service crashed: %s", exc, exc_info=True)
            console.print(f"[red]⚠️ Bot异常退出: {exc}[/red]")
        finally:
            try:
                await service.stop()
            except Exception:
                pass
            console.print("[dim]WeChat Bot Service 已停止[/dim]")

        if not stop_event.is_set():
            console.print(f"[yellow]🔄 {restart_delay}秒后重启Bot...[/yellow]")
            for _ in range(restart_delay):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1)
            restart_delay = min(restart_delay * 2, 300)  # exponential backoff, max 5 min
