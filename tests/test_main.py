from fastapi.testclient import TestClient

from app.main import GREETING, app


client = TestClient(app)


def test_health_returns_plain_text_greeting():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == GREETING


def test_chat_returns_plain_text_greeting():
    response = client.post("/chat", content="hello")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == GREETING
