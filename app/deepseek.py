import httpx

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-chat"

_history: list[dict] = []
_client = httpx.Client(timeout=30.0)


def chat(message: str, api_key: str = "") -> str:
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
