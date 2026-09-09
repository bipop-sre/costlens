"""Tests for WeChat Work bot service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from costlens.config import Settings
from costlens.wechat_bot import WeChatBotService, HELP_TEXT


@pytest.fixture
def mock_settings():
    """Create settings with bot credentials."""
    return Settings(
        openai_api_key="sk-test-key",
        openai_model="gpt-4o",
        openai_base_url="https://api.openai.com/v1",
        wechat_work_bot_id="test-bot-id-12345678",
        wechat_work_bot_secret="test-bot-secret",
        enabled_providers="aws",
    )


@pytest.fixture
def mock_frame():
    """Create a mock WebSocket frame matching real WeChat Bot structure."""
    frame = MagicMock()
    frame.body = {
        "msgid": "test-msg-001",
        "aibotid": "test-bot-id",
        "chattype": "single",
        "msgtype": "text",
        "text": {"content": "这个月花了多少钱"},
        "from": {"userid": "user-123"},
    }
    frame.headers = {"req_id": "req-001"}
    return frame


@pytest.fixture
def mock_enter_frame():
    """Create a mock enter-chat frame."""
    frame = MagicMock()
    frame.body = {"from": {"userid": "user-123"}}
    return frame


class TestWeChatBotService:
    """Test WeChatBotService initialization and lifecycle."""

    def test_init(self, mock_settings):
        service = WeChatBotService(mock_settings)
        assert service.settings is mock_settings
        assert not service.is_running
        assert service.session_count == 0
        assert service.connected_chatids == set()

    def test_init_default_settings(self):
        """Service can be created with default settings (no args)."""
        service = WeChatBotService()
        assert service.settings is not None

    @pytest.mark.asyncio
    async def test_start_without_credentials(self):
        """Start should raise ValueError when bot credentials are missing."""
        settings = Settings(
            openai_api_key="sk-test",
            wechat_work_bot_id="",
            wechat_work_bot_secret="",
        )
        service = WeChatBotService(settings)
        with pytest.raises(ValueError, match="WECHAT_WORK_BOT_ID"):
            await service.start()

    @pytest.mark.asyncio
    async def test_start_and_stop(self, mock_settings):
        """Start should connect, stop should clean up."""
        with patch("costlens.wechat_bot.CostLensAgent") as mock_agent_cls:
            mock_agent = AsyncMock()
            mock_agent_cls.return_value = mock_agent

            with patch("wecom_aibot_sdk.WSClient") as mock_ws_cls:
                mock_ws = AsyncMock()
                mock_ws_cls.return_value = mock_ws

                service = WeChatBotService(mock_settings)
                await service.start()

                assert service.is_running
                mock_ws.connect_async.assert_called_once()
                assert mock_ws.on.call_count == 2

                await service.stop()

                assert not service.is_running
                mock_ws.disconnect.assert_called_once()
                mock_agent.close.assert_called_once()
                assert service.session_count == 0

    @pytest.mark.asyncio
    async def test_start_idempotent(self, mock_settings):
        """Calling start twice should not create duplicate connections."""
        with patch("costlens.wechat_bot.CostLensAgent") as mock_agent_cls:
            mock_agent_cls.return_value = AsyncMock()

            with patch("wecom_aibot_sdk.WSClient") as mock_ws_cls:
                mock_ws = AsyncMock()
                mock_ws_cls.return_value = mock_ws

                service = WeChatBotService(mock_settings)
                await service.start()
                await service.start()  # second call should be no-op

                assert mock_ws.connect_async.call_count == 1
                await service.stop()


class TestSessionManagement:
    """Test per-chatid session management."""

    def test_get_session_creates_new(self, mock_settings):
        service = WeChatBotService(mock_settings)
        with patch("costlens.wechat_bot.CostLensAgent"):
            service._agent = MagicMock()
            session = service.get_session("chat-001")
            assert session.session_id == "chat-001"
            assert service.session_count == 1

    def test_get_session_reuses_existing(self, mock_settings):
        service = WeChatBotService(mock_settings)
        with patch("costlens.wechat_bot.CostLensAgent"):
            service._agent = MagicMock()
            session1 = service.get_session("chat-001")
            session2 = service.get_session("chat-001")
            assert session1 is session2
            assert service.session_count == 1

    def test_get_session_different_chatids(self, mock_settings):
        service = WeChatBotService(mock_settings)
        with patch("costlens.wechat_bot.CostLensAgent"):
            service._agent = MagicMock()
            s1 = service.get_session("chat-001")
            s2 = service.get_session("chat-002")
            assert s1 is not s2
            assert service.session_count == 2


class TestMessageRouting:
    """Test _handle_message routing to commands and AI chat."""

    @pytest.fixture
    def service_with_mocks(self, mock_settings):
        """Service with mocked agent and ws_client."""
        with patch("costlens.wechat_bot.CostLensAgent"):
            service = WeChatBotService(mock_settings)
            service._agent = MagicMock()
            service._ws_client = AsyncMock()
            service._running = True
            return service

    @pytest.mark.asyncio
    async def test_handle_enter(self, service_with_mocks, mock_enter_frame):
        service = service_with_mocks
        await service._handle_enter(mock_enter_frame)
        assert "user-123" in service.connected_chatids

    @pytest.mark.asyncio
    async def test_handle_message_empty_content(self, service_with_mocks):
        service = service_with_mocks
        frame = MagicMock()
        frame.body = {"msgtype": "text", "text": {"content": ""}, "from": {"userid": "user-123"}}
        await service._handle_message(frame)
        # No reply should be sent for empty messages
        service._ws_client.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_non_text_ignored(self, service_with_mocks):
        """Non-text messages (e.g. image) should be ignored."""
        service = service_with_mocks
        frame = MagicMock()
        frame.body = {"msgtype": "image", "image": {"url": "http://example.com"}, "from": {"userid": "user-123"}}
        await service._handle_message(frame)
        service._ws_client.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_help_command(self, service_with_mocks, mock_frame):
        service = service_with_mocks
        mock_frame.body["text"]["content"] = "/help"
        await service._handle_message(mock_frame)
        service._ws_client.reply.assert_called_once()
        call_args = service._ws_client.reply.call_args
        body = call_args[0][1]
        assert body["msgtype"] == "markdown"
        assert "CostLens" in body["markdown"]["content"]

    @pytest.mark.asyncio
    async def test_handle_help_chinese(self, service_with_mocks, mock_frame):
        service = service_with_mocks
        mock_frame.body["text"]["content"] = "帮助"
        await service._handle_message(mock_frame)
        service._ws_client.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_clear_command(self, service_with_mocks, mock_frame):
        service = service_with_mocks
        # Session key is userid for single chats
        session = service.get_session("user-123")
        session.history = [{"role": "user", "content": "test"}]

        mock_frame.body["text"]["content"] = "/clear"
        await service._handle_message(mock_frame)

        assert len(session.history) == 0
        service._ws_client.reply.assert_called_once()
        body = service._ws_client.reply.call_args[0][1]
        assert "清空" in body["markdown"]["content"]

    @pytest.mark.asyncio
    async def test_handle_ai_chat(self, service_with_mocks, mock_frame):
        """Normal messages should be routed to AI agent with streaming."""
        service = service_with_mocks
        mock_frame.body["text"]["content"] = "这个月花了多少钱"

        # Mock the agent's stream_chat to yield tokens
        async def mock_stream(*args, **kwargs):
            for token in ["本月", "成本", "总计", " $1,234.56"]:
                yield token

        service._agent.stream_chat = mock_stream

        await service._handle_message(mock_frame)

        # Should have called reply_stream multiple times
        assert service._ws_client.reply_stream.call_count >= 2
        # Last call should have finish=True
        last_call = service._ws_client.reply_stream.call_args_list[-1]
        assert last_call[1]["finish"] is True

    @pytest.mark.asyncio
    async def test_handle_ai_chat_error_fallback(self, service_with_mocks, mock_frame):
        """If AI agent raises, should send error message."""
        service = service_with_mocks
        mock_frame.body["text"]["content"] = "查询成本"

        async def mock_stream_error(*args, **kwargs):
            raise ConnectionError("API unreachable")
            yield  # make it an async generator

        service._agent.stream_chat = mock_stream_error

        await service._handle_message(mock_frame)

        # Should fall back to error markdown reply
        service._ws_client.reply.assert_called_once()
        body = service._ws_client.reply.call_args[0][1]
        assert "处理失败" in body["markdown"]["content"]


class TestBroadcast:
    """Test broadcast to all connected chats."""

    @pytest.mark.asyncio
    async def test_broadcast_to_connected_chats(self, mock_settings):
        with patch("costlens.wechat_bot.CostLensAgent"):
            service = WeChatBotService(mock_settings)
            service._ws_client = AsyncMock()
            service._running = True
            service._connected_chatids = {"chat-001", "chat-002", "chat-003"}

            count = await service.broadcast("Hello everyone!")
            assert count == 3
            assert service._ws_client.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_broadcast_when_not_running(self, mock_settings):
        service = WeChatBotService(mock_settings)
        count = await service.broadcast("Hello!")
        assert count == 0

    @pytest.mark.asyncio
    async def test_broadcast_partial_failure(self, mock_settings):
        with patch("costlens.wechat_bot.CostLensAgent"):
            service = WeChatBotService(mock_settings)
            service._ws_client = AsyncMock()
            service._running = True
            service._connected_chatids = {"chat-001", "chat-002"}

            call_count = 0

            async def mock_send(chatid, body):
                nonlocal call_count
                call_count += 1
                if chatid == "chat-002":
                    raise Exception("Connection lost")

            service._ws_client.send_message = mock_send

            count = await service.broadcast("Test")
            assert count == 1


class TestHelpText:
    """Test help text content."""

    def test_help_text_contains_commands(self):
        assert "/help" in HELP_TEXT
        assert "/clear" in HELP_TEXT
        assert "成本" in HELP_TEXT

    def test_help_text_contains_capabilities(self):
        assert "多云" in HELP_TEXT
        assert "趋势" in HELP_TEXT
        assert "异常" in HELP_TEXT
        assert "优化" in HELP_TEXT


class TestNotifierIntegration:
    """Test WeChatWorkBotNotifier integration with bot service."""

    def test_notifier_has_set_bot_service(self):
        from costlens.notifications import WeChatWorkBotNotifier
        notifier = WeChatWorkBotNotifier("bot-id", "secret")
        assert notifier._bot_service is None

        mock_service = MagicMock()
        notifier.set_bot_service(mock_service)
        assert notifier._bot_service is mock_service

    @pytest.mark.asyncio
    async def test_notifier_delegates_to_bot_service(self):
        from costlens.notifications import WeChatWorkBotNotifier
        notifier = WeChatWorkBotNotifier("bot-id", "secret")
        notifier._client = AsyncMock()
        notifier._ws_connected = True

        mock_service = AsyncMock()
        notifier.set_bot_service(mock_service)

        frame = MagicMock()
        frame.body = {"msgtype": "text", "text": {"content": "hello"}, "from": {"userid": "user-123"}}
        await notifier._on_message(frame)

        mock_service._handle_message.assert_called_once_with(frame)

    @pytest.mark.asyncio
    async def test_notifier_fallback_without_service(self):
        from costlens.notifications import WeChatWorkBotNotifier
        notifier = WeChatWorkBotNotifier("bot-id", "secret")
        notifier._client = AsyncMock()
        notifier._ws_connected = True

        frame = MagicMock()
        frame.body = {"msgtype": "text", "text": {"content": "帮助"}, "from": {"userid": "user-123"}}
        frame.headers = {"req_id": "req-001"}
        await notifier._on_message(frame)

        # Should use static reply since no bot_service
        notifier._client.reply.assert_called_once()
        body = notifier._client.reply.call_args[0][1]
        assert "CostLens" in body["markdown"]["content"]
