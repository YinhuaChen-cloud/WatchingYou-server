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
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Hello!")) as mock_post:
        reply = ds.chat("Hi")

    assert reply == "Hello!"


def test_chat_appends_to_history():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("I'm fine")):
        ds.chat("How are you?")

    assert len(ds._history) == 3  # system + user + assistant
    assert ds._history[1] == {"role": "user", "content": "How are you?"}
    assert ds._history[2] == {"role": "assistant", "content": "I'm fine"}


def test_chat_sends_full_history_on_second_message():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Hi there")) as mock_post:
        ds.chat("Hello")

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Sure!")) as mock_post:
        ds.chat("Can you help?")

    called_messages = mock_post.call_args[1]["json"]["messages"]
    assert len(called_messages) == 4  # system + user1 + assistant1 + user2
    assert called_messages[0]["role"] == "system"
    assert called_messages[1]["role"] == "user"
    assert called_messages[2]["role"] == "assistant"
    assert called_messages[3]["role"] == "user"


def test_chat_raises_on_api_error():
    import app.deepseek as ds
    ds.reset_history()

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
    ds.reset_history()

    error_resp = MagicMock()
    error_resp.status_code = 500
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=error_resp
    )

    with patch.object(ds._client, "post", return_value=error_resp):
        with pytest.raises(httpx.HTTPStatusError):
            ds.chat("Hello")

    assert len(ds._history) == 1  # only system prompt remains


def test_reset_history_restores_system_prompt_only():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("ok")):
        ds.chat("msg1")
        ds.chat("msg2")

    assert len(ds._history) > 1

    ds.reset_history()

    assert len(ds._history) == 1
    assert ds._history[0] == {"role": "system", "content": ds._SYSTEM_PROMPT["content"]}


def test_parse_reminder_request_returns_structured_result_and_raw_reply():
    import app.deepseek as ds
    ds.reset_history()
    raw_reply = '{"is_reminder": true, "remind_at": "2026-06-26T02:30:00+00:00", "task": "开会", "confirmation": "行，2:30 记得去开会，别装没看见。"}'

    with patch.object(ds._client, "post", return_value=make_deepseek_response(raw_reply)):
        result = ds.parse_reminder_request("2:30 提醒我开会")

    assert result.raw_reply == raw_reply
    assert result.data == {
        "is_reminder": True,
        "remind_at": "2026-06-26T02:30:00+00:00",
        "task": "开会",
        "confirmation": "行，2:30 记得去开会，别装没看见。",
    }


def test_parse_reminder_request_returns_none_data_for_plain_text_reply():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("这只是普通回复")):
        result = ds.parse_reminder_request("你好吗")

    assert result.raw_reply == "这只是普通回复"
    assert result.data is None


def test_parse_reminder_request_handles_non_reminder_json():
    import app.deepseek as ds
    ds.reset_history()
    raw_reply = '{"is_reminder": false, "confirmation": "这不是提醒。"}'

    with patch.object(ds._client, "post", return_value=make_deepseek_response(raw_reply)):
        result = ds.parse_reminder_request("你好")

    assert result.raw_reply == raw_reply
    assert result.data == {
        "is_reminder": False,
        "confirmation": "这不是提醒。",
    }


def test_generate_reminder_message_uses_history_and_returns_reply():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("收到")):
        ds.chat("你好")

    with patch.object(ds._client, "post", return_value=make_deepseek_response("别发呆了，该开会了。")) as mock_post:
        reply = ds.generate_reminder_message("开会")

    assert reply == "别发呆了，该开会了。"
    called_messages = mock_post.call_args[1]["json"]["messages"]
    assert len(called_messages) == 4
    assert called_messages[0]["role"] == "system"
    assert called_messages[1] == {"role": "user", "content": "你好"}
    assert called_messages[2] == {"role": "assistant", "content": "收到"}
    assert called_messages[3]["role"] == "user"
    assert "开会" in called_messages[3]["content"]
