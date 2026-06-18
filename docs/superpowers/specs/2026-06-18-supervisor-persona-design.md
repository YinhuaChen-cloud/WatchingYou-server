# WatchingYou Server — 学习工作监督员 Persona Design

## Overview

给 WatchingYou Server 注入一个"学习工作监督员"的 AI 性格。通过在 DeepSeek 对话历史里预置一条 system prompt 来实现，同时支持用户发送 `/restart` 指令重置对话历史。

## 改动范围

只改动两个文件：

- `app/deepseek.py` — 预置 system prompt，新增 `reset_history()` 函数
- `app/main.py` — `/chat` 端点检测 `/restart` 指令，调用重置逻辑

## System Prompt

```
你是一个学习工作监督员，名叫"监督员"。你的职责是盯着用户学习和工作。
你的性格：阴阳怪气，说话带刺，擅长冷嘲热讽，但不会真的骂人。

行为规则：
1. 如果用户问的是学习、编程、工作相关的问题，正常认真回答，可以在结尾加一句轻微的嘲讽（如"这你都不知道？"）。
2. 如果用户问的是与学习/工作无关的问题（闲聊、娱乐、吃饭等），不要回答问题本身，而是用阴阳怪气的语气把用户怼回去，催他去学习或工作。
3. 始终用中文回复。
4. 回复简短有力，不超过100字。
```

## 架构与数据流

### `/restart` 指令处理

```
Client POST /chat (body: "/restart")
  → main.py 检测到 body == "/restart"
  → 调用 deepseek.reset_history()，将 _history 重置为只含 system prompt 的初始状态
  → 返回 HTTP 200，文本："对话已重置。"（不调用 DeepSeek API）
```

### 正常对话流（不变）

```
Client POST /chat (body: 用户消息)
  → main.py 提取消息文本
  → deepseek.chat() 追加到 _history，调用 DeepSeek API
  → DeepSeek 返回 AI 回复
  → deepseek.chat() 追加 AI 回复到 _history
  → main.py 返回 AI 回复（text/plain）
```

## 代码设计

### `app/deepseek.py`

```python
_SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "你是一个学习工作监督员，名叫"监督员"。..."
    ),
}

_history: list[dict] = [dict(_SYSTEM_PROMPT)]

def reset_history() -> None:
    global _history
    _history = [dict(_SYSTEM_PROMPT)]
```

`chat()` 函数不变。

### `app/main.py`

```python
@app.post("/chat")
async def chat(request: Request) -> Response:
    body = (await request.body()).decode("utf-8").strip()
    if not body:
        return Response(content="message body is required", status_code=400, ...)

    if body == "/restart":
        deepseek.reset_history()
        return Response(content="对话已重置。", media_type="text/plain")

    # 正常 DeepSeek 调用（现有逻辑不变）
    ...
```

## 端点行为

| 请求 | 行为 | 响应 |
|---|---|---|
| `POST /chat` body=`/restart` | 重置历史，不调 DeepSeek | HTTP 200, `"对话已重置。"` |
| `POST /chat` body=普通消息 | 正常调用 DeepSeek | HTTP 200, AI 回复 |
| `POST /chat` body=空 | 不变 | HTTP 400 |
| `GET /health` | 不变 | HTTP 200, `"Hello from WatchingYou-server"` |

## 测试

- `test_deepseek.py`：测试 `reset_history()` 正确重置 `_history` 到只含 system prompt 的状态
- `test_main.py`：测试 `/restart` 端点返回 200 和正确文本，并验证历史被清除
