# Reminder Proactive Messages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create natural-language reminders through `/chat`, schedule them in memory on the server, and deliver generated reminder messages to Android through the existing `/poll` proactive-message flow.

**Architecture:** The server adds DeepSeek reminder parsing/generation helpers and an in-memory `ReminderScheduler` that publishes into the existing `ProactiveMessageBroker`. The fixed six-minute auto publisher is removed from FastAPI startup. Android keeps the existing foreground long-poll loop and extends proactive-message parsing so `type="error"` stores a red error chat bubble.

**Tech Stack:** Python 3, FastAPI, asyncio, pytest, httpx, Kotlin, Android Room, coroutines, JUnit.

---

## Repositories and Commit Boundaries

This feature spans two sibling git repositories:

- Server repo: `/home/chenyinhua/WatchingYou/WatchingYou-server`
- Android repo: `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP`

Commit server changes inside `WatchingYou-server`. Commit Android changes inside `WatchingYou-Android-APP`. Do not run git commands from `/home/chenyinhua/WatchingYou` because it is not a git repository.

## File Structure

### Server files

- Modify: `WatchingYou-server/app/proactive_messages.py`
  - Adds a `type` field to queued proactive messages.
  - Keeps `/poll` backward-compatible for normal AI messages.
  - Leaves `run_auto_publisher()` available but unused by FastAPI startup.
- Modify: `WatchingYou-server/tests/test_proactive_messages.py`
  - Updates broker tests for `type="ai"`, `type="error"`, and the current queue size.
- Modify: `WatchingYou-server/app/deepseek.py`
  - Adds structured reminder parsing.
  - Adds reminder-trigger message generation.
  - Keeps reminder-related calls in the shared conversation history.
- Modify: `WatchingYou-server/tests/test_deepseek.py`
  - Tests reminder parsing success, non-reminder parsing, raw parse failure, and reminder generation history behavior.
- Create: `WatchingYou-server/app/reminders.py`
  - Owns parsed reminder data, time validation, in-memory scheduling, task cancellation, and trigger-time publishing.
- Create: `WatchingYou-server/tests/test_reminders.py`
  - Tests scheduling, invalid times, generation success, generation failure, and shutdown cancellation.
- Modify: `WatchingYou-server/app/main.py`
  - Stops starting the fixed auto publisher.
  - Initializes `ReminderScheduler`.
  - Attempts reminder parsing in `/chat` before normal chat fallback.
- Modify: `WatchingYou-server/tests/test_main.py`
  - Tests `/chat` reminder behavior, `/poll` message type response, and lifespan behavior without the fixed auto publisher.
- Modify: `WatchingYou-server/README.md`
  - Documents reminder behavior and removes the claim that six-minute test messages are auto-generated.

### Android files

- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`
  - Adds `ProactiveMessageType`.
  - Extends `ProactiveMessage` with `type`, defaulting to `AI`.
  - Parses `/poll` JSON `type` and treats missing `type` as `AI`.
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`
  - Tests `type="ai"`, missing `type`, `type="error"`, and unknown type fallback.
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`
  - Stores `type="error"` proactive messages as `Sender.ERROR`.
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`
  - Tests error proactive messages become red error chat messages.
- Modify: `WatchingYou-Android-APP/README.md`
  - Documents reminder-driven proactive messages and removes the six-minute verification step.

---

## Task 1: Add Proactive Message Types on the Server

**Files:**
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-server/app/proactive_messages.py`
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_proactive_messages.py`

- [ ] **Step 1: Write failing tests for proactive message types**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_proactive_messages.py`.

Change `TestProactiveMessage.test_construction` to:

```python
    def test_construction(self):
        msg = ProactiveMessage(content="hello", timestamp=1234567890)
        assert msg.content == "hello"
        assert msg.timestamp == 1234567890
        assert msg.type == "ai"
```

Change `TestProactiveMessage.test_to_dict` to:

```python
    def test_to_dict(self):
        msg = ProactiveMessage(content="世界", timestamp=999)
        d = msg.to_dict()
        assert d == {"content": "世界", "timestamp": 999, "type": "ai"}
```

Add this test under `TestProactiveMessage`:

```python
    def test_to_dict_includes_error_type(self):
        msg = ProactiveMessage(content="主动消息生成失败", timestamp=999, type="error")
        d = msg.to_dict()
        assert d == {"content": "主动消息生成失败", "timestamp": 999, "type": "error"}
```

Change `TestConstants.test_constants_have_expected_values` to match the current queue size:

```python
    def test_constants_have_expected_values(self):
        assert AUTO_MESSAGE_INTERVAL_SECONDS == 360
        assert AUTO_MESSAGE_CONTENT == "每隔6min自动发送消息"
        assert POLL_DEFAULT_TIMEOUT_SECONDS == 30
        assert POLL_MIN_TIMEOUT_SECONDS == 1
        assert POLL_MAX_TIMEOUT_SECONDS == 60
        assert MAX_QUEUE_SIZE == 1000
```

Add this broker test under `TestProactiveMessageBroker`:

```python
    def test_publish_accepts_message_type(self):
        async def _test():
            broker = ProactiveMessageBroker(now_ms=lambda: 42)
            await broker.publish("主动消息生成失败", message_type="error")
            result = await broker.poll()
            assert result.content == "主动消息生成失败"
            assert result.timestamp == 42
            assert result.type == "error"

        _run(_test())
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_proactive_messages.py -v
```

Expected: FAIL because `ProactiveMessage` has no `type` field and `publish()` has no `message_type` parameter.

- [ ] **Step 3: Implement proactive message type support**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-server/app/proactive_messages.py`.

Change the dataclass and `publish()` signature to:

```python
@dataclass(frozen=True)
class ProactiveMessage:
    content: str
    timestamp: int
    type: str = "ai"

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)
```

```python
    async def publish(
        self,
        content: str,
        timestamp_ms: Optional[int] = None,
        message_type: str = "ai",
    ) -> None:
        timestamp = timestamp_ms if timestamp_ms is not None else self._now_ms()
        msg = ProactiveMessage(content=content, timestamp=timestamp, type=message_type)
        async with self._condition:
            if len(self._queue) >= self.max_queue_size:
                self._queue.popleft()
            self._queue.append(msg)
            self._condition.notify_all()
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_proactive_messages.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit server proactive message type support**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
git add app/proactive_messages.py tests/test_proactive_messages.py
git commit -m "feat: add proactive message types"
```

---

## Task 2: Add DeepSeek Reminder Parsing and Generation

**Files:**
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-server/app/deepseek.py`
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_deepseek.py`

- [ ] **Step 1: Write failing DeepSeek reminder tests**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_deepseek.py`.

Add imports near the top:

```python
import json
```

Add these tests after `test_chat_does_not_append_to_history_on_api_error`:

```python
def test_parse_reminder_request_returns_structured_result_and_raw_reply():
    import app.deepseek as ds
    ds.reset_history()
    raw = json.dumps({
        "is_reminder": True,
        "remind_at": "2026-06-25T14:30:00+08:00",
        "task": "开会",
        "confirmation": "行，14:30 我提醒你开会。",
    }, ensure_ascii=False)

    with patch.object(ds._client, "post", return_value=make_deepseek_response(raw)):
        result = ds.parse_reminder_request("哟，2:30 提醒我开会", api_key="sk-test")

    assert result.raw_reply == raw
    assert result.data == {
        "is_reminder": True,
        "remind_at": "2026-06-25T14:30:00+08:00",
        "task": "开会",
        "confirmation": "行，14:30 我提醒你开会。",
    }
    assert ds._history[-2]["role"] == "user"
    assert ds._history[-1] == {"role": "assistant", "content": raw}


def test_parse_reminder_request_returns_none_data_for_plain_text_reply():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("你这时间说清楚点。")):
        result = ds.parse_reminder_request("提醒我", api_key="sk-test")

    assert result.raw_reply == "你这时间说清楚点。"
    assert result.data is None


def test_parse_reminder_request_handles_non_reminder_json():
    import app.deepseek as ds
    ds.reset_history()
    raw = json.dumps({"is_reminder": False}, ensure_ascii=False)

    with patch.object(ds._client, "post", return_value=make_deepseek_response(raw)):
        result = ds.parse_reminder_request("你好", api_key="sk-test")

    assert result.raw_reply == raw
    assert result.data == {"is_reminder": False}


def test_generate_reminder_message_uses_history_and_returns_reply():
    import app.deepseek as ds
    ds.reset_history()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("别磨蹭了，该开会了。")):
        reply = ds.generate_reminder_message("开会", api_key="sk-test")

    assert reply == "别磨蹭了，该开会了。"
    assert ds._history[-2]["role"] == "user"
    assert "开会" in ds._history[-2]["content"]
    assert ds._history[-1] == {"role": "assistant", "content": "别磨蹭了，该开会了。"}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_deepseek.py -v
```

Expected: FAIL because `parse_reminder_request` and `generate_reminder_message` do not exist.

- [ ] **Step 3: Implement DeepSeek reminder helpers**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-server/app/deepseek.py`.

Add imports:

```python
import json
from dataclasses import dataclass
from typing import Any, Optional
```

Add this dataclass after `_client`:

```python
@dataclass(frozen=True)
class ReminderParseResult:
    raw_reply: str
    data: Optional[dict[str, Any]]
```

Add these functions after `chat()`:

```python
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
        "判断下面用户消息是否是在设置提醒。"
        "如果是提醒，只返回 JSON："
        "{\"is_reminder\":true,\"remind_at\":\"YYYY-MM-DDTHH:MM:SS+08:00\","
        "\"task\":\"提醒事项\",\"confirmation\":\"给用户的中文确认回复\"}。"
        "如果不是提醒，只返回 JSON：{\"is_reminder\":false}。"
        "如果时间或事项不清楚，直接用中文回复用户，不要返回 JSON。"
        "用户消息：" + message
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
    prompt = (
        "现在到了用户设置的提醒时间。"
        "请用你的学习工作监督员人设，用中文生成一句不超过 100 字的提醒。"
        "提醒事项：" + task
    )
    return _send_history_message(prompt, api_key=api_key)
```

Change the existing `chat()` body to reuse `_send_history_message`:

```python
def chat(message: str, api_key: str = "") -> str:
    return _send_history_message(message, api_key=api_key)
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_deepseek.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit DeepSeek reminder helpers**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
git add app/deepseek.py tests/test_deepseek.py
git commit -m "feat: add reminder prompts"
```

---

## Task 3: Add the Server Reminder Scheduler

**Files:**
- Create: `/home/chenyinhua/WatchingYou/WatchingYou-server/app/reminders.py`
- Create: `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_reminders.py`

- [ ] **Step 1: Write failing scheduler tests**

Create `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_reminders.py`:

```python
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.proactive_messages import ProactiveMessageBroker
from app.reminders import ParsedReminder, ReminderScheduler, parse_remind_at


def _run(coro):
    return asyncio.run(coro)


def test_parse_remind_at_accepts_future_iso_timestamp():
    target = parse_remind_at("2099-01-01T09:30:00+08:00")
    assert target.year == 2099
    assert target.tzinfo is not None


def test_parse_remind_at_rejects_invalid_timestamp():
    assert parse_remind_at("not a time") is None


def test_schedule_rejects_past_time():
    async def _test():
        broker = ProactiveMessageBroker()
        scheduler = ReminderScheduler(
            broker=broker,
            api_key="sk-test",
            generate_message=lambda task, api_key: "unused",
            now=lambda: datetime(2026, 6, 25, 15, 0, tzinfo=timezone.utc),
        )
        reminder = ParsedReminder(
            remind_at=datetime(2026, 6, 25, 14, 0, tzinfo=timezone.utc),
            task="开会",
            confirmation="行，14:00 我提醒你开会。",
        )

        scheduled = scheduler.schedule(reminder)

        assert scheduled is False
        assert scheduler.active_count == 0

    _run(_test())


def test_schedule_publishes_generated_message_when_due():
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 123)
        scheduler = ReminderScheduler(
            broker=broker,
            api_key="sk-test",
            generate_message=lambda task, api_key: "别磨蹭了，该开会了。",
            now=lambda: datetime.now(timezone.utc),
        )
        reminder = ParsedReminder(
            remind_at=datetime.now(timezone.utc) + timedelta(milliseconds=10),
            task="开会",
            confirmation="行，马上提醒你开会。",
        )

        scheduled = scheduler.schedule(reminder)
        assert scheduled is True
        message = await broker.poll(timeout_seconds=1)

        assert message.content == "别磨蹭了，该开会了。"
        assert message.timestamp == 123
        assert message.type == "ai"
        await scheduler.shutdown()

    _run(_test())


def test_schedule_publishes_error_message_when_generation_fails():
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 456)

        def fail_generate(task, api_key):
            raise RuntimeError("DeepSeek down")

        scheduler = ReminderScheduler(
            broker=broker,
            api_key="sk-test",
            generate_message=fail_generate,
            now=lambda: datetime.now(timezone.utc),
        )
        reminder = ParsedReminder(
            remind_at=datetime.now(timezone.utc) + timedelta(milliseconds=10),
            task="开会",
            confirmation="行，马上提醒你开会。",
        )

        scheduled = scheduler.schedule(reminder)
        assert scheduled is True
        message = await broker.poll(timeout_seconds=1)

        assert message.content == "主动消息生成失败"
        assert message.timestamp == 456
        assert message.type == "error"
        await scheduler.shutdown()

    _run(_test())


def test_shutdown_cancels_active_tasks():
    async def _test():
        broker = ProactiveMessageBroker()
        scheduler = ReminderScheduler(
            broker=broker,
            api_key="sk-test",
            generate_message=lambda task, api_key: "unused",
            now=lambda: datetime.now(timezone.utc),
        )
        reminder = ParsedReminder(
            remind_at=datetime.now(timezone.utc) + timedelta(hours=1),
            task="开会",
            confirmation="行，1 小时后提醒你开会。",
        )

        assert scheduler.schedule(reminder) is True
        assert scheduler.active_count == 1
        await scheduler.shutdown()

        assert scheduler.active_count == 0

    _run(_test())
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_reminders.py -v
```

Expected: FAIL because `app.reminders` does not exist.

- [ ] **Step 3: Implement the scheduler**

Create `/home/chenyinhua/WatchingYou/WatchingYou-server/app/reminders.py`:

```python
import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from starlette.concurrency import run_in_threadpool

from app.proactive_messages import ProactiveMessageBroker

REMINDER_GENERATION_ERROR_MESSAGE = "主动消息生成失败"


@dataclass(frozen=True)
class ParsedReminder:
    remind_at: datetime
    task: str
    confirmation: str


def parse_remind_at(value: str) -> Optional[datetime]:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class ReminderScheduler:
    def __init__(
        self,
        broker: ProactiveMessageBroker,
        api_key: str,
        generate_message: Callable[[str, str], str],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._broker = broker
        self._api_key = api_key
        self._generate_message = generate_message
        self._now = now
        self._tasks: set[asyncio.Task] = set()

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def schedule(self, reminder: ParsedReminder) -> bool:
        delay_seconds = (reminder.remind_at - self._now()).total_seconds()
        if delay_seconds <= 0:
            return False
        task = asyncio.create_task(self._run_reminder(reminder, delay_seconds))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    async def _run_reminder(self, reminder: ParsedReminder, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)
        try:
            content = await run_in_threadpool(
                self._generate_message,
                reminder.task,
                self._api_key,
            )
            await self._broker.publish(content, message_type="ai")
        except Exception:
            await self._broker.publish(
                REMINDER_GENERATION_ERROR_MESSAGE,
                message_type="error",
            )
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_reminders.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit scheduler**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
git add app/reminders.py tests/test_reminders.py
git commit -m "feat: add in-memory reminder scheduler"
```

---

## Task 4: Wire Reminder Scheduling into FastAPI

**Files:**
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-server/app/main.py`
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_main.py`

- [ ] **Step 1: Write failing FastAPI tests**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-server/tests/test_main.py`.

Add imports near the top:

```python
from datetime import datetime, timedelta, timezone
```

Add these tests after `test_restart_with_whitespace_works`:

```python
def test_chat_schedules_reminder_and_returns_confirmation(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    parse_result = type("ParseResult", (), {
        "raw_reply": "raw confirmation",
        "data": {
            "is_reminder": True,
            "remind_at": future,
            "task": "开会",
            "confirmation": "行，1 小时后我提醒你开会。",
        },
    })()

    with patch("app.main.deepseek.parse_reminder_request", return_value=parse_result), \
         patch.object(client.app.state.reminder_scheduler, "schedule", return_value=True) as mock_schedule:
        response = client.post("/chat", content="1 小时后提醒我开会", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "行，1 小时后我提醒你开会。"
    mock_schedule.assert_called_once()
    scheduled_reminder = mock_schedule.call_args.args[0]
    assert scheduled_reminder.task == "开会"
    assert scheduled_reminder.confirmation == "行，1 小时后我提醒你开会。"


def test_chat_returns_raw_reply_when_reminder_parse_is_plain_text(client):
    parse_result = type("ParseResult", (), {
        "raw_reply": "你这提醒说得跟谜语一样。",
        "data": None,
    })()

    with patch("app.main.deepseek.parse_reminder_request", return_value=parse_result), \
         patch("app.main.deepseek.chat") as mock_chat:
        response = client.post("/chat", content="提醒我", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "你这提醒说得跟谜语一样。"
    mock_chat.assert_not_called()


def test_chat_falls_back_to_normal_chat_for_non_reminder(client):
    parse_result = type("ParseResult", (), {
        "raw_reply": "{\"is_reminder\": false}",
        "data": {"is_reminder": False},
    })()

    with patch("app.main.deepseek.parse_reminder_request", return_value=parse_result), \
         patch("app.main.deepseek.chat", return_value="普通回复") as mock_chat:
        response = client.post("/chat", content="你好", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "普通回复"
    mock_chat.assert_called_once_with("你好", api_key="sk-test")


def test_chat_returns_raw_reply_when_reminder_time_is_invalid(client):
    parse_result = type("ParseResult", (), {
        "raw_reply": "这个时间已经过去了，别穿越。",
        "data": {
            "is_reminder": True,
            "remind_at": "not a timestamp",
            "task": "开会",
            "confirmation": "行。",
        },
    })()

    with patch("app.main.deepseek.parse_reminder_request", return_value=parse_result), \
         patch.object(client.app.state.reminder_scheduler, "schedule") as mock_schedule:
        response = client.post("/chat", content="昨天提醒我开会", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.text == "这个时间已经过去了，别穿越。"
    mock_schedule.assert_not_called()
```

Change `TestPollEndpoint.test_poll_returns_queued_message_when_published` expected JSON to:

```python
        assert response.json() == {"content": "test message", "timestamp": 123456789, "type": "ai"}
```

Change `TestPollEndpoint.test_poll_default_timeout_when_not_specified` expected JSON to:

```python
        assert response.json() == {"content": "immediate", "timestamp": 222, "type": "ai"}
```

Change `TestPollEndpoint.test_poll_returns_queued_message_immediately` expected JSON to:

```python
        assert response.json() == {"content": "pre-queued", "timestamp": 333, "type": "ai"}
```

Replace `TestLifespan.test_lifespan_starts_and_stops_auto_publisher` with:

```python
    def test_lifespan_does_not_start_fixed_auto_publisher(self):
        with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
            with patch("app.proactive_messages.run_auto_publisher") as mock_auto_publisher:
                import importlib
                import app.main as app_main_module
                importlib.reload(app_main_module)

                with TestClient(app_main_module.app) as test_client:
                    response = test_client.get("/health")
                    assert response.status_code == 200

                mock_auto_publisher.assert_not_called()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_main.py -v
```

Expected: FAIL because `main.py` has not wired reminder parsing and still starts the fixed auto publisher.

- [ ] **Step 3: Wire scheduler and `/chat` reminder flow**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-server/app/main.py`.

Change imports:

```python
from app.proactive_messages import ProactiveMessageBroker
from app.reminders import ParsedReminder, ReminderScheduler, parse_remind_at
```

Remove module globals for `_auto_publisher_stop` and `_auto_publisher_task`.

Add a scheduler global after `proactive_broker`:

```python
reminder_scheduler = ReminderScheduler(
    broker=proactive_broker,
    api_key=_api_key,
    generate_message=deepseek.generate_reminder_message,
)
```

Replace `lifespan()` with:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.reminder_scheduler = reminder_scheduler
    yield
    await reminder_scheduler.shutdown()
```

Add this helper above `/chat`:

```python
def _parsed_reminder_from_data(data: dict) -> ParsedReminder | None:
    if data.get("is_reminder") is not True:
        return None
    remind_at_value = data.get("remind_at")
    task = data.get("task")
    confirmation = data.get("confirmation")
    if not isinstance(remind_at_value, str):
        return None
    if not isinstance(task, str) or not task.strip():
        return None
    if not isinstance(confirmation, str) or not confirmation.strip():
        return None
    remind_at = parse_remind_at(remind_at_value)
    if remind_at is None:
        return None
    return ParsedReminder(remind_at=remind_at, task=task.strip(), confirmation=confirmation.strip())
```

Replace the normal DeepSeek call block in `/chat` with this flow:

```python
    try:
        parse_result = await run_in_threadpool(
            deepseek.parse_reminder_request,
            body,
            api_key=_api_key,
        )
        if parse_result.data is None:
            return Response(content=parse_result.raw_reply, media_type="text/plain")
        if parse_result.data.get("is_reminder") is True:
            reminder = _parsed_reminder_from_data(parse_result.data)
            if reminder is None:
                return Response(content=parse_result.raw_reply, media_type="text/plain")
            if not reminder_scheduler.schedule(reminder):
                return Response(content=parse_result.raw_reply, media_type="text/plain")
            return Response(content=reminder.confirmation, media_type="text/plain")

        reply = await run_in_threadpool(deepseek.chat, body, api_key=_api_key)
        return Response(content=reply, media_type="text/plain")
```

Keep the existing `except httpx.HTTPStatusError` and generic `except Exception` blocks unchanged after this code.

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest tests/test_main.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all server tests**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest -v
```

Expected: PASS.

- [ ] **Step 6: Commit FastAPI reminder wiring**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
git add app/main.py tests/test_main.py
git commit -m "feat: schedule reminders from chat"
```

---

## Task 5: Add Android Proactive Message Type Parsing

**Files:**
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`

- [ ] **Step 1: Write failing Android API parsing tests**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`.

Change `pollProactiveMessageParsesJsonResponse` response body and assertion:

```kotlin
        server.start(
            responseBody = """{"content":"proactive message","timestamp":123456789,"type":"ai"}""",
            statusCode = 200
        )

        val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 999L })

        assertEquals(ProactiveMessage("proactive message", 123456789L, ProactiveMessageType.AI), result)
```

Change `pollProactiveMessageFallsBackToLegacyPlainText` assertion:

```kotlin
        assertEquals(ProactiveMessage("legacy proactive message", 555L, ProactiveMessageType.AI), result)
```

Change `pollProactiveMessageFallsBackOnMissingField` assertion:

```kotlin
        assertEquals(ProactiveMessage(rawBody, 777L, ProactiveMessageType.AI), result)
```

Change `pollProactiveMessageFallsBackOnWrongFieldTypes` assertion:

```kotlin
        assertEquals(ProactiveMessage(rawBody, 888L, ProactiveMessageType.AI), result)
```

Change `pollProactiveMessageUsesCustomTimeout` assertion:

```kotlin
        assertEquals(ProactiveMessage("ok", 42L, ProactiveMessageType.AI), result)
```

Add these tests after `pollProactiveMessageParsesJsonResponse`:

```kotlin
    @Test
    fun pollProactiveMessageTreatsMissingTypeAsAi() {
        server.start(
            responseBody = """{"content":"proactive message","timestamp":123456789}""",
            statusCode = 200
        )

        val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 999L })

        assertEquals(ProactiveMessage("proactive message", 123456789L, ProactiveMessageType.AI), result)
    }

    @Test
    fun pollProactiveMessageParsesErrorType() {
        server.start(
            responseBody = """{"content":"主动消息生成失败","timestamp":123456789,"type":"error"}""",
            statusCode = 200
        )

        val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 999L })

        assertEquals(ProactiveMessage("主动消息生成失败", 123456789L, ProactiveMessageType.ERROR), result)
    }

    @Test
    fun pollProactiveMessageTreatsUnknownTypeAsAi() {
        server.start(
            responseBody = """{"content":"proactive message","timestamp":123456789,"type":"surprise"}""",
            statusCode = 200
        )

        val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 999L })

        assertEquals(ProactiveMessage("proactive message", 123456789L, ProactiveMessageType.AI), result)
    }
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.WatchingYouApiTest'
```

Expected: FAIL because `ProactiveMessageType` does not exist and `ProactiveMessage` only has two fields.

- [ ] **Step 3: Implement Android API type parsing**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`.

Replace the proactive message model with:

```kotlin
enum class ProactiveMessageType { AI, ERROR }

data class ProactiveMessage(
    val content: String,
    val timestamp: Long,
    val type: ProactiveMessageType = ProactiveMessageType.AI
)
```

Replace the successful JSON return in `parseProactiveMessage()` with:

```kotlin
            val type = when (json.optString("type", "ai")) {
                "error" -> ProactiveMessageType.ERROR
                else -> ProactiveMessageType.AI
            }
            ProactiveMessage(contentValue, timestampValue.toLong(), type)
```

Leave the existing fallback returns as `ProactiveMessage(body, now())`; the default type makes them `AI`.

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.WatchingYouApiTest'
```

Expected: PASS.

- [ ] **Step 5: Commit Android API type parsing**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
git add app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt
git commit -m "feat: parse proactive message types"
```

---

## Task 6: Store Error Proactive Messages as Red Error Bubbles

**Files:**
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`

- [ ] **Step 1: Write failing coordinator test**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`.

Add this test after `successfulPollStoresAiMessageAndCallsOnMessageStored`:

```kotlin
    @Test
    fun errorPollStoresErrorMessageAndCallsOnMessageStored() = runBlocking {
        val dao = RecordingChatMessageDao()
        val stored = CountDownLatch(1)
        val pollCount = java.util.concurrent.atomic.AtomicInteger(0)
        val coordinator = ProactiveMessageSyncCoordinator(
            dao = dao,
            appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
            ioDispatcher = Dispatchers.Default,
            baseUrlProvider = { "http://server" },
            pollMessage = { _, _ ->
                val count = pollCount.incrementAndGet()
                if (count == 1) {
                    ProactiveMessage("主动消息生成失败", 987654321L, ProactiveMessageType.ERROR)
                } else {
                    null
                }
            },
            onStatusChanged = {},
            onMessageStored = { stored.countDown() },
            retryDelayMs = 0L
        )

        coordinator.start()
        assertTrue("onMessageStored was not called", stored.await(2, TimeUnit.SECONDS))
        coordinator.stop()
        coordinator.awaitIdle()

        assertEquals(1, dao.inserted.size)
        val inserted = dao.inserted[0]
        assertEquals("主动消息生成失败", inserted.content)
        assertEquals(Sender.ERROR, inserted.sender)
        assertEquals(987654321L, inserted.timestamp)
    }
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ProactiveMessageSyncCoordinatorTest.errorPollStoresErrorMessageAndCallsOnMessageStored'
```

Expected: FAIL because the coordinator stores every proactive message as `Sender.AI`.

- [ ] **Step 3: Implement sender mapping**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`.

Replace the inserted message construction with:

```kotlin
                                Message(
                                    content = message.content,
                                    sender = when (message.type) {
                                        ProactiveMessageType.AI -> Sender.AI
                                        ProactiveMessageType.ERROR -> Sender.ERROR
                                    },
                                    timestamp = message.timestamp
                                )
```

- [ ] **Step 4: Run coordinator tests and verify they pass**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ProactiveMessageSyncCoordinatorTest'
```

Expected: PASS.

- [ ] **Step 5: Commit Android error proactive storage**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
git add app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt
git commit -m "feat: render proactive errors as error messages"
```

---

## Task 7: Update Documentation and Run Full Verification

**Files:**
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-server/README.md`
- Modify: `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/README.md`

- [ ] **Step 1: Update server README**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-server/README.md`.

Replace the `/poll` behavior bullet with:

```markdown
- `GET /poll?timeout_seconds=30` — long-polling endpoint for proactive messages. Returns `200 application/json` with `{"content": "...", "timestamp": <unix-epoch-ms>, "type": "ai"}` for normal proactive messages, `type: "error"` for red error proactive messages, or `204 No Content` when the poll times out without a message. `timeout_seconds` is optional (default 30, clamped to 1–60). Proactive delivery is foreground-only; no vivo Push, FCM, or background service is involved in this version.
```

Add this behavior bullet after `/restart`:

```markdown
- `POST /chat` with a natural-language reminder request such as `哟，2:30 提醒我开会` — asks DeepSeek to parse the reminder, schedules it in memory, and immediately returns a confirmation reply. When the reminder fires, the server asks DeepSeek to generate a reminder message and queues it for `/poll`. Scheduled reminders are lost if the server restarts.
```

Replace the old six-minute verification block with:

```bash
# Queue behavior is now reminder-driven. Start the server, send a near-future reminder,
# then poll until the reminder message is returned.
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "1 分钟后提醒我开会"
curl http://127.0.0.1:8000/poll
```

- [ ] **Step 2: Update Android README**

Edit `/home/chenyinhua/WatchingYou/WatchingYou-Android-APP/README.md`.

Replace the proactive sync feature bullet with:

```markdown
- 服务端主动消息同步：APP 在前台时通过长轮询（long polling）接收服务端主动消息，显示为左侧 AI 消息。服务端 `/poll` 返回 JSON 格式 `{"content":"...","timestamp":<unix-epoch-ms>,"type":"ai"}`；`type` 缺失时按 `ai` 处理，`type="error"` 时显示为红色错误消息。APP 使用服务端提供的排队时间戳存入 Room 数据库。仅前台生效，后台、锁屏、APP 被杀死时均不轮询，不支持后台推送（vivo Push / FCM / 后台服务均不在此版本范围内）。
```

Replace the manual six-minute verification step with:

```markdown
4. 在聊天输入框发送一个短时间提醒，例如 `1 分钟后提醒我开会`，确认服务端立即返回 AI 确认回复。
5. 等到提醒时间后，确认左侧 AI 消息气泡中出现服务端生成的提醒文案。
6. 如果服务端到点生成主动消息失败，确认 APP 显示红色错误消息 `主动消息生成失败`。
```

- [ ] **Step 3: Run all server tests**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
pytest -v
```

Expected: PASS.

- [ ] **Step 4: Run all Android unit tests**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 5: Build Android debug APK**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
./gradlew assembleDebug
```

Expected: BUILD SUCCESSFUL and APK at `app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Step 6: Commit documentation updates**

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
git add README.md
git commit -m "docs: describe reminder proactive messages"
```

Run:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-Android-APP
git add README.md
git commit -m "docs: describe reminder proactive messages"
```

---

## Manual Verification

After both repositories pass automated tests:

1. Start the server:

```bash
cd /home/chenyinhua/WatchingYou/WatchingYou-server
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

2. Send a near-future reminder:

```bash
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "1 分钟后提醒我开会"
```

Expected: plain-text AI confirmation.

3. Poll for the reminder:

```bash
curl http://127.0.0.1:8000/poll
```

Expected after the reminder fires: JSON with `content`, `timestamp`, and `type":"ai"`.

4. Install and open the Android app, register the server URL, send `1 分钟后提醒我开会`, and confirm:

- Immediate AI confirmation appears after the user's message.
- A reminder AI bubble appears after the target time.
- No fixed `每隔6min自动发送消息` messages appear.
- A forced trigger-generation failure shows `主动消息生成失败` as a red error bubble.

## Self-Review Notes

- Spec coverage: server parsing, in-memory scheduling, shared DeepSeek history, `/poll` type field, Android error rendering, fixed auto-publisher shutdown, no persistence, and tests are covered.
- Placeholder scan: no task relies on unspecified implementation details or deferred work.
- Type consistency: server uses `type` values `ai` and `error`; Android maps them to `ProactiveMessageType.AI` and `ProactiveMessageType.ERROR`; storage maps `ERROR` to `Sender.ERROR`.
