from unittest.mock import patch
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
        import importlib
        import app.main
        importlib.reload(app.main)
        return TestClient(app.main.app)


def test_health_returns_plain_text_greeting(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello from WatchingYou-server"


def test_chat_returns_ai_reply(client):
    with patch("app.main.deepseek.chat", return_value="Hello from DeepSeek"):
        response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello from DeepSeek"


def test_chat_empty_body_returns_400(client):
    response = client.post("/chat", content="", headers={"Content-Type": "text/plain"})

    assert response.status_code == 400


def test_chat_deepseek_http_error_returns_502(client):
    mock_response = httpx.Response(500, text="Internal Server Error")
    error = httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://x"), response=mock_response)

    with patch("app.main.deepseek.chat", side_effect=error):
        response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 502
    assert "500" in response.text


def test_chat_network_error_returns_502(client):
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
        assert response.json() == {"content": "test message", "timestamp": 123456789}

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
        assert response.json() == {"content": "immediate", "timestamp": 222}

    def test_poll_returns_queued_message_immediately(self, client_and_broker):
        """When a message is queued before poll, it returns immediately without waiting."""
        client, broker = client_and_broker

        async def _publish():
            await broker.publish("pre-queued", timestamp_ms=333)

        asyncio.run(_publish())

        response = client.get("/poll", params={"timeout_seconds": 5})
        assert response.status_code == 200
        assert response.json() == {"content": "pre-queued", "timestamp": 333}


# ---------------------------------------------------------------------------
# Lifespan tests
# ---------------------------------------------------------------------------

class TestLifespan:
    def test_lifespan_starts_and_stops_auto_publisher(self):
        """
        Verify that the lifespan starts run_auto_publisher on startup
        and stops it cleanly on shutdown. We monkeypatch run_auto_publisher
        to track calls without actually running the real auto publisher.
        """
        started = False
        stopped = False

        async def mock_run_auto_publisher(broker, stop_event=None):
            nonlocal started
            started = True
            try:
                # Block until stop_event is set, simulating the real publisher
                await stop_event.wait()
            finally:
                nonlocal stopped
                stopped = True

        with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
            # Patch the original function in proactive_messages so that
            # importlib.reload picks up the mock when re-executing the import.
            with patch("app.proactive_messages.run_auto_publisher", side_effect=mock_run_auto_publisher):
                import importlib
                import app.main as app_main_module
                importlib.reload(app_main_module)

                # Entering TestClient context runs the lifespan startup
                with TestClient(app_main_module.app) as test_client:
                    assert app_main_module._auto_publisher_task is not None
                    assert started, "auto publisher should have been started"

                # After exiting TestClient, lifespan shutdown should have run
                assert stopped, "auto publisher should have been stopped"
                assert app_main_module._auto_publisher_task is None
                assert app_main_module._auto_publisher_stop is None

    def test_existing_routes_unaffected_by_lifespan(self, client):
        """Sanity check that /health still works with lifespan."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.text == "Hello from WatchingYou-server"