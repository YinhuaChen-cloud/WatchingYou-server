import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-v4-pro"

_SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        '你是一个学习工作监督员，名叫“监督员”。你的职责是盯着用户学习和工作。\n'
        '你的性格：阴阳怪气，说话带刺，擅长冷嘲热讽，但不会真的骂人。\n'
        '\n'
        '行为规则：\n'
        '1. 如果用户问的是学习、编程、工作相关的问题，正常认真回答，可以在结尾加一句轻微的嘲讽（如“这你都不知道？”）。\n'
        '2. 如果用户问的是与学习/工作无关的问题（闲聊、娱乐、吃饭等），不要回答问题本身，而是用阴阳怪气的语气把用户怼回去，催他去学习或工作。\n'
        '3. 始终用中文回复。\n'
        '4. 回复简短有力，不超过100字。'
    ),
}

_history: list[dict] = [dict(_SYSTEM_PROMPT)]

_client = httpx.Client(timeout=30.0)


@dataclass(frozen=True)
class ReminderParseResult:
    raw_reply: str
    data: Optional[dict[str, Any]]


def reset_history() -> None:
    global _history
    _history = [dict(_SYSTEM_PROMPT)]


def _send_history_message(message: str, api_key: str = "") -> str:
    _history.append({"role": "user", "content": message})
    try:
        response = _client.post(
            _DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": _MODEL, "messages": list(_history)},
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        _history.append({"role": "assistant", "content": reply})
        return reply
    except Exception:
        _history.pop()
        raise


def parse_reminder_request(message: str, api_key: str = "") -> ReminderParseResult:
    prompt = (
        "请判断这句话是不是提醒请求。"
        "如果是或不是，都只返回一个 JSON 对象，不要输出额外文字。"
        "字段：is_reminder、remind_at、task、confirmation。"
        f"用户消息：{message}"
    )
    raw_reply = _send_history_message(prompt, api_key=api_key)
    try:
        data = json.loads(raw_reply)
    except json.JSONDecodeError:
        return ReminderParseResult(raw_reply=raw_reply, data=None)
    if not isinstance(data, dict):
        return ReminderParseResult(raw_reply=raw_reply, data=None)
    return ReminderParseResult(raw_reply=raw_reply, data=data)


def generate_reminder_message(task: str, api_key: str = "") -> str:
    prompt = f"提醒时间到了，任务是：{task}。请用监督员的人设生成一条简短中文提醒。"
    return _send_history_message(prompt, api_key=api_key)


def chat(message: str, api_key: str = "") -> str:
    return _send_history_message(message, api_key=api_key)