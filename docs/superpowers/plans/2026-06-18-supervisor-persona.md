# 学习工作监督员 Persona 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 WatchingYou Server 注入"学习工作监督员"性格，通过 system prompt 让 DeepSeek 以阴阳怪气的语气 PUA 用户，同时支持 `/restart` 指令重置对话。

**Architecture:** 纯 system prompt 方案。在 `deepseek.py` 中预置一条 system 消息作为对话历史的第一条，永不删除。`main.py` 的 `/chat` 端点检测 `/restart` 指令，调用 `reset_history()` 重置历史到初始状态。

**Tech Stack:** Python 3, FastAPI, httpx, pytest

---

### Task 1: 修改 deepseek.py — 预置 system prompt 和 reset_history

**Files:**
- Modify: `app/deepseek.py`

- [ ] **Step 1: 添加 system prompt 常量和 reset_history 函数，修改 `_history` 初始值**

```python
import httpx

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-chat"

_SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "你是一个学习工作监督员，名叫"监督员"。你的职责是盯着用户学习和工作。\n"
        "你的性格：阴阳怪气，说话带刺，擅长冷嘲热讽，但不会真的骂人。\n"
        "\n"
        "行为规则：\n"
        "1. 如果用户问的是学习、编程、工作相关的问题，正常认真回答，可以在结尾加一句轻微的嘲讽（如"这你都不知道？"）。\n"
        "2. 如果用户问的是与学习/工作无关的问题（闲聊、娱乐、吃饭等），不要回答问题本身，而是用阴阳怪气的语气把用户怼回去，催他去学习或工作。\n"
        "3. 始终用中文回复。\n"
        "4. 回复简短有力，不超过100字。"
    ),
}

_history: list[dict] = [dict(_SYSTEM_PROMPT)]

_client = httpx.Client(timeout=30.0)


def reset_history() -> None:
    global _history
    _history = [dict(_SYSTEM_PROMPT)]


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
```

- [ ] **Step 2: 运行现有 deepseek 测试，确认 system prompt 的存在不影响现有功能**

```bash
cd ~/WatchingYou/WatchingYou-server && python -m pytest tests/test_deepseek.py -v
```

Expected: 部分测试可能失败（因为 `_history.clear()` 现在会清除 system prompt，测试需要更新）

- [ ] **Step 3: 更新测试以适配 system prompt**

打开 `tests/test_deepseek.py`，将每个测试中的 `ds._history.clear()` 改为 `ds.reset_history()`，并调整断言中 history 长度的期望值（加上 system prompt 这条）。

`test_chat_appends_to_history` 需要改为：

```python
def test_chat_appends_to_history():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("I'm fine")):
        ds.chat("How are you?")

    assert len(ds._history) == 3  # system + user + assistant
    assert ds._history[1] == {"role": "user", "content": "How are you?"}
    assert ds._history[2] == {"role": "assistant", "content": "I'm fine"}
```

`test_chat_sends_full_history_on_second_message` 需要改为：

```python
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
```

`test_chat_does_not_append_to_history_on_api_error` 需要改为：

```python
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
```

- [ ] **Step 4: 添加 reset_history 测试**

在 `tests/test_deepseek.py` 末尾添加：

```python
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
```

- [ ] **Step 5: 运行测试确认全部通过**

```bash
cd ~/WatchingYou/WatchingYou-server && python -m pytest tests/test_deepseek.py -v
```

Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
cd ~/WatchingYou/WatchingYou-server && git add app/deepseek.py tests/test_deepseek.py && git commit -m "feat: add supervisor persona system prompt and reset_history"
```

---

### Task 2: 修改 main.py — 添加 /restart 指令处理

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: 在 `/chat` 端点中添加 `/restart` 检测**

```python
import httpx
from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import load_config
from app import deepseek

GREETING = "Hello from WatchingYou-server"

_config = load_config()
_api_key = _config["deepseek_api_key"]

app = FastAPI(title="WatchingYou Server")


@app.get("/health", response_class=Response)
def health() -> Response:
    return Response(content=GREETING, media_type="text/plain")


@app.post("/chat", response_class=Response)
async def chat(request: Request) -> Response:
    body = (await request.body()).decode("utf-8").strip()
    if not body:
        return Response(content="message body is required", status_code=400, media_type="text/plain")

    if body == "/restart":
        deepseek.reset_history()
        return Response(content="对话已重置。", media_type="text/plain")

    try:
        reply = await run_in_threadpool(deepseek.chat, body, api_key=_api_key)
        return Response(content=reply, media_type="text/plain")
    except httpx.HTTPStatusError as e:
        error_text = f"DeepSeek API error {e.response.status_code}: {e.response.text}"
        return Response(content=error_text, status_code=502, media_type="text/plain")
    except Exception as e:
        return Response(content=f"upstream error: {e}", status_code=502, media_type="text/plain")
```

- [ ] **Step 2: 运行现有 main 测试，确保已有测试不受影响**

```bash
cd ~/WatchingYou/WatchingYou-server && python -m pytest tests/test_main.py -v
```

Expected: 全部 PASS

- [ ] **Step 3: 添加 `/restart` 测试**

在 `tests/test_main.py` 末尾添加：

```python
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
```

- [ ] **Step 4: 运行测试确认全部通过**

```bash
cd ~/WatchingYou/WatchingYou-server && python -m pytest tests/test_main.py -v
```

Expected: 全部 PASS（包括新增的 2 个 `/restart` 测试）

- [ ] **Step 5: Commit**

```bash
cd ~/WatchingYou/WatchingYou-server && git add app/main.py tests/test_main.py && git commit -m "feat: add /restart command to reset conversation history"
```

---

### Task 3: 验证完整流程

- [ ] **Step 1: 运行全部测试**

```bash
cd ~/WatchingYou/WatchingYou-server && python -m pytest tests/ -v
```

Expected: 全部 PASS

- [ ] **Step 2: 手动验证 /restart 不调用 DeepSeek API**

这个可以通过检查测试中 `deepseek.chat` 没有被调用来验证（已在 test_restart 中通过 mock 验证）。
