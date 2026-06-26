from unittest.mock import patch
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient

from app.deepseek import ReminderParseResult


@pytest.fixture
def client():
    with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
        import importlib
        import app.main
        importlib.reload(app.main)
        with TestClient(app.main.app) as test_client:
            yield test_client


def test_health_returns_plain_text_greeting(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello from WatchingYou-server"


def test_chat_returns_ai_reply(client):
    with patch(
        "app.main.deepseek.parse_reminder_request",
        return_value=ReminderParseResult(raw_reply='{"is_reminder": false}', data={"is_reminder": False}),
    ):
        with patch("app.main.deepseek.chat", return_value="Hello from DeepSeek"):
            response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello from DeepSeek"


def test_chat_reminder_returns_confirmation_and_schedules(client):
    parse_result = ReminderParseResult(
        raw_reply='{"is_reminder": true}',
        data={
            "is_reminder": True,
            "remind_at": "2999-01-01T00:00:00+00:00",
            "task": "开会",
            "confirmation": "行，到点我叫你。",
        },
    )

    with patch("app.main.deepseek.parse_reminder_request", return_value=parse_result):
        with patch.object(client.app.state.reminder_scheduler, "schedule", return_value=True) as mock_schedule:
            response = client.post("/chat", content="提醒我开会", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "行，到点我叫你。"
    scheduled = mock_schedule.call_args.args[0]
    assert scheduled.task == "开会"
    assert scheduled.confirmation == "行，到点我叫你。"


def test_chat_parse_failure_returns_raw_reply_and_does_not_schedule(client):
    parse_result = ReminderParseResult(raw_reply="这是原始回复", data=None)

    with patch("app.main.deepseek.parse_reminder_request", return_value=parse_result):
        with patch.object(client.app.state.reminder_scheduler, "schedule") as mock_schedule:
            response = client.post("/chat", content="你好", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "这是原始回复"
    mock_schedule.assert_not_called()


def test_chat_invalid_reminder_time_returns_raw_reply(client):
    parse_result = ReminderParseResult(
        raw_reply="提醒时间无效",
        data={
            "is_reminder": True,
            "remind_at": "not-a-time",
            "task": "开会",
            "confirmation": "行",
        },
    )

    with patch("app.main.deepseek.parse_reminder_request", return_value=parse_result):
        with patch.object(client.app.state.reminder_scheduler, "schedule") as mock_schedule:
            response = client.post("/chat", content="提醒我开会", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "提醒时间无效"
    mock_schedule.assert_not_called()


def test_chat_empty_body_returns_400(client):
    response = client.post("/chat", content="", headers={"Content-Type": "text/plain"})

    assert response.status_code == 400


def test_chat_deepseek_http_error_returns_502(client):
    mock_response = httpx.Response(500, text="Internal Server Error")
    error = httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://x"), response=mock_response)

    with patch(
        "app.main.deepseek.parse_reminder_request",
        return_value=ReminderParseResult(raw_reply='{"is_reminder": false}', data={"is_reminder": False}),
    ):
        with patch("app.main.deepseek.chat", side_effect=error):
            response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 502
    assert "500" in response.text


def test_chat_network_error_returns_502(client):
    with patch(
        "app.main.deepseek.parse_reminder_request",
        return_value=ReminderParseResult(raw_reply='{"is_reminder": false}', data={"is_reminder": False}),
    ):
        with patch("app.main.deepseek.chat", side_effect=Exception("connection refused")):
            response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 502


def test_restart_returns_200_and_resets_history(client):
    with patch("app.main.deepseek.reset_history") as mock_reset:
        response = client.post("/chat", content="/restart", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "对话已重置。"
    mock_reset.assert_called_once()


def test_restart_with_whitespace_works(client):
    with patch("app.main.deepseek.reset_history") as mock_reset:
        response = client.post("/chat", content="  /restart  ", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "对话已重置。"
    mock_reset.assert_called_once()


# ---------------------------------------------------------------------------
# Factored-out fixture for poll tests that need the broker and client together
# ---------------------------------------------------------------------------

@pytest.fixture
def client_and_broker():
    """Yields (TestClient, ProactiveMessageBroker) with a fresh app module."""
    with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
        import importlib
        import app.main
        importlib.reload(app.main)
        yield TestClient(app.main.app), app.main.proactive_broker


# ---------------------------------------------------------------------------
# /poll endpoint tests
# ---------------------------------------------------------------------------

class TestPollEndpoint:
    def test_poll_returns_queued_message_when_published(self, client_and_broker):
        client, broker = client_and_broker

        async def _publish():
            await broker.publish("test message", timestamp_ms=123456789)

        asyncio.run(_publish())

        response = client.get("/poll", params={"timeout_seconds": 1})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"content": "test message", "timestamp": 123456789, "type": "ai"}

    def test_poll_returns_204_on_timeout(self, client_and_broker):
        client, broker = client_and_broker
        response = client.get("/poll", params={"timeout_seconds": 0.1})
        assert response.status_code == 204
        assert response.text == ""

    def test_poll_passes_timeout_clamping(self, client_and_broker):
        """
        timeout_seconds=0.001 is clamped to 1s by the broker.
        Server returns 204 after the clamped timeout with no message.
        """
        client, broker = client_and_broker
        response = client.get("/poll", params={"timeout_seconds": 0.001})
        assert response.status_code == 204

    def test_poll_default_timeout_when_not_specified(self, client_and_broker):
        """Without timeout_seconds, broker uses default 30s.
        We pre-queue a message so it returns immediately."""
        client, broker = client_and_broker

        async def _publish():
            await broker.publish("immediate", timestamp_ms=222)

        asyncio.run(_publish())

        response = client.get("/poll")
        assert response.status_code == 200
        assert response.json() == {"content": "immediate", "timestamp": 222, "type": "ai"}

    def test_poll_returns_queued_message_immediately(self, client_and_broker):
        """When a message is queued before poll, it returns immediately without waiting."""
        client, broker = client_and_broker

        async def _publish():
            await broker.publish("pre-queued", timestamp_ms=333)

        asyncio.run(_publish())

        response = client.get("/poll", params={"timeout_seconds": 5})
        assert response.status_code == 200
        assert response.json() == {"content": "pre-queued", "timestamp": 333, "type": "ai"}


# ---------------------------------------------------------------------------
# Lifespan tests
# ---------------------------------------------------------------------------

class TestLifespan:
    def test_lifespan_exposes_reminder_scheduler_and_cleans_up(self):
        with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
            import importlib
            import app.main as app_main_module
            importlib.reload(app_main_module)

            with patch.object(app_main_module.deepseek, "generate_reminder_message", return_value="提醒"):
                with TestClient(app_main_module.app) as test_client:
                    assert test_client.app.state.reminder_scheduler is not None
                    assert test_client.app.state.reminder_scheduler.active_count == 0

                assert app_main_module.app.state.reminder_scheduler.active_count == 0

    def test_existing_routes_unaffected_by_lifespan(self, client):
        """Sanity check that /health still works with lifespan."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.text == "Hello from WatchingYou-server"