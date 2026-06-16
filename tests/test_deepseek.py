import pytest
import httpx
from unittest.mock import patch, MagicMock


def make_deepseek_response(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return mock_resp


def test_chat_returns_ai_reply():
    import app.deepseek as ds
    ds._history.clear()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Hello!")) as mock_post:
        reply = ds.chat("Hi")

    assert reply == "Hello!"


def test_chat_appends_to_history():
    import app.deepseek as ds
    ds._history.clear()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("I'm fine")):
        ds.chat("How are you?")

    assert len(ds._history) == 2
    assert ds._history[0] == {"role": "user", "content": "How are you?"}
    assert ds._history[1] == {"role": "assistant", "content": "I'm fine"}


def test_chat_sends_full_history_on_second_message():
    import app.deepseek as ds
    ds._history.clear()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Hi there")) as mock_post:
        ds.chat("Hello")

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Sure!")) as mock_post:
        ds.chat("Can you help?")

    called_messages = mock_post.call_args[1]["json"]["messages"]
    assert len(called_messages) == 3
    assert called_messages[0]["role"] == "user"
    assert called_messages[1]["role"] == "assistant"
    assert called_messages[2]["role"] == "user"


def test_chat_raises_on_api_error():
    import app.deepseek as ds
    ds._history.clear()

    error_resp = MagicMock()
    error_resp.status_code = 401
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized", request=MagicMock(), response=error_resp
    )

    with patch.object(ds._client, "post", return_value=error_resp):
        with pytest.raises(httpx.HTTPStatusError):
            ds.chat("Hello")


def test_chat_does_not_append_to_history_on_api_error():
    import app.deepseek as ds
    ds._history.clear()

    error_resp = MagicMock()
    error_resp.status_code = 500
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=error_resp
    )

    with patch.object(ds._client, "post", return_value=error_resp):
        with pytest.raises(httpx.HTTPStatusError):
            ds.chat("Hello")

    assert len(ds._history) == 0
