from unittest.mock import patch
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
