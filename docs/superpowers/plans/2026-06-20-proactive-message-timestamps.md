# Proactive Message Timestamps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve server enqueue time for proactive messages so Android displays old queued messages with the correct timestamp separator.

**Architecture:** The server queue stores structured proactive messages with `content` and epoch-millisecond `timestamp`, and `/poll` returns JSON for queued messages. Android parses the JSON into a `ProactiveMessage`, falls back to legacy plain text when needed, and stores the server timestamp in Room so the existing `messagesToChatItems()` separator logic works unchanged.

**Tech Stack:** FastAPI + pytest on WatchingYou-server; Kotlin + Android SDK + Room + JUnit on WatchingYou-Android-APP.

---

## Scope Check

This plan spans two repositories because the protocol change is not useful unless both sides agree on it. The server and Android changes are tightly coupled around the `/poll` contract, so one implementation plan is acceptable. Make one working, tested commit in each repository when the relevant tasks pass.

## File Structure

### WatchingYou-server

- Modify: `WatchingYou-server/app/proactive_messages.py`
  - Owns proactive message constants, queue model, broker behavior, and auto publisher.
  - Add `ProactiveMessage` dataclass and timestamp generation.
- Modify: `WatchingYou-server/app/main.py`
  - Owns HTTP routes.
  - Change `/poll` success response from `text/plain` to JSON.
- Modify: `WatchingYou-server/tests/test_proactive_messages.py`
  - Unit tests for constants, broker queue behavior, explicit timestamps, generated timestamps, and auto publisher.
- Modify: `WatchingYou-server/tests/test_main.py`
  - Endpoint tests for `/poll` JSON response and existing `204` timeout behavior.
- Modify: `WatchingYou-server/README.md`
  - Update `/poll` protocol, interval, message text, and curl verification notes.

### WatchingYou-Android-APP

- Modify: `WatchingYou-Android-APP/app/build.gradle`
  - Add `testImplementation 'org.json:json:20240303'` so local JVM tests can execute Android-compatible JSON parsing.
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`
  - Add `ProactiveMessage` data class.
  - Parse JSON `/poll` responses with legacy plain-text fallback.
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`
  - Change `pollMessage` dependency from returning `String?` to returning `ProactiveMessage?`.
  - Store `message.content` and `message.timestamp`.
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/MainActivity.kt`
  - Wrap `WatchingYouApi.pollProactiveMessage` so it matches the new coordinator function type.
  - Remove the `now` constructor argument from `ProactiveMessageSyncCoordinator` construction.
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`
  - Test JSON parsing, legacy fallback, 204, errors, and custom timeout URL.
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`
  - Update test lambdas to return `ProactiveMessage?`.
  - Verify server timestamp is stored instead of local `now()`.
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ChatItemTest.kt`
  - Add explicit tests for the `> 5 minutes` separator threshold.
- Modify: `WatchingYou-Android-APP/README.md`
  - Update manual verification to 6 minutes and the new proactive message text.

---

## Task 1: Server proactive message model and broker

**Files:**
- Modify: `WatchingYou-server/tests/test_proactive_messages.py`
- Modify: `WatchingYou-server/app/proactive_messages.py`

- [ ] **Step 1: Update failing server broker tests**

Edit `WatchingYou-server/tests/test_proactive_messages.py`.

Update the imports at the top to include `ProactiveMessage`:

```python
from app.proactive_messages import (
    AUTO_MESSAGE_CONTENT,
    AUTO_MESSAGE_INTERVAL_SECONDS,
    MAX_QUEUE_SIZE,
    POLL_DEFAULT_TIMEOUT_SECONDS,
    POLL_MAX_TIMEOUT_SECONDS,
    POLL_MIN_TIMEOUT_SECONDS,
    ProactiveMessage,
    ProactiveMessageBroker,
    clamp_poll_timeout,
    run_auto_publisher,
)
```

In `TestConstants.test_constants_have_expected_values`, replace the interval and content assertions with:

```python
assert AUTO_MESSAGE_INTERVAL_SECONDS == 360
assert AUTO_MESSAGE_CONTENT == "每隔6min自动发送消息"
```

Replace `TestProactiveMessageBroker.test_poll_returns_message_immediately_when_queued` with:

```python
def test_poll_returns_message_immediately_when_queued(self):
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 12345)
        await broker.publish("hello")
        result = await broker.poll()
        assert result == ProactiveMessage(content="hello", timestamp=12345)

    _run(_test())
```

Add this test after it:

```python
def test_publish_accepts_explicit_timestamp(self):
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 99999)
        await broker.publish("historical", timestamp_ms=123)
        result = await broker.poll()
        assert result == ProactiveMessage(content="historical", timestamp=123)

    _run(_test())
```

Replace `TestProactiveMessageBroker.test_poll_fifo_order` with:

```python
def test_poll_fifo_order(self):
    async def _test():
        clock_values = iter([1000, 2000, 3000])
        broker = ProactiveMessageBroker(now_ms=lambda: next(clock_values))
        await broker.publish("first")
        await broker.publish("second")
        await broker.publish("third")
        assert await broker.poll() == ProactiveMessage(content="first", timestamp=1000)
        assert await broker.poll() == ProactiveMessage(content="second", timestamp=2000)
        assert await broker.poll() == ProactiveMessage(content="third", timestamp=3000)

    _run(_test())
```

Replace `TestProactiveMessageBroker.test_publish_beyond_max_drops_oldest` with:

```python
def test_publish_beyond_max_drops_oldest(self):
    async def _test():
        broker = ProactiveMessageBroker(max_queue_size=3, now_ms=lambda: 123)
        await broker.publish("a", timestamp_ms=1)
        await broker.publish("b", timestamp_ms=2)
        await broker.publish("c", timestamp_ms=3)
        await broker.publish("d", timestamp_ms=4)  # drops "a"
        assert await broker.poll() == ProactiveMessage(content="b", timestamp=2)
        assert await broker.poll() == ProactiveMessage(content="c", timestamp=3)
        assert await broker.poll() == ProactiveMessage(content="d", timestamp=4)
        result = await broker.poll(timeout_seconds=0.05)
        assert result is None

    _run(_test())
```

Replace `TestProactiveMessageBroker.test_multiple_waiters_all_woken` with:

```python
def test_multiple_waiters_all_woken(self):
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 123)

        async def waiter():
            return await broker.poll(timeout_seconds=5)

        task1 = asyncio.create_task(waiter())
        task2 = asyncio.create_task(waiter())
        await asyncio.sleep(0.1)
        await broker.publish("msg")
        results = await asyncio.gather(task1, task2)
        assert results.count(ProactiveMessage(content="msg", timestamp=123)) == 1
        assert results.count(None) == 1

    _run(_test())
```

Replace `TestProactiveMessageBroker.test_poll_with_default_timeout_uses_30_seconds` with:

```python
def test_poll_with_default_timeout_uses_30_seconds(self):
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 456)

        async def delayed_publish():
            await asyncio.sleep(0.1)
            await broker.publish("delayed")

        asyncio.create_task(delayed_publish())
        start = time.monotonic()
        result = await broker.poll()
        elapsed = time.monotonic() - start
        assert result == ProactiveMessage(content="delayed", timestamp=456)
        assert elapsed < 1.0

    _run(_test())
```

In `TestRunAutoPublisher.test_publishes_after_interval_not_immediately`, replace the message assertion with:

```python
assert result is not None
assert result.content == AUTO_MESSAGE_CONTENT
assert isinstance(result.timestamp, int)
```

In `TestRunAutoPublisher.test_publishes_repeatedly`, replace the loop assertion with:

```python
for msg in messages:
    assert msg.content == AUTO_MESSAGE_CONTENT
    assert isinstance(msg.timestamp, int)
```

In `TestRunAutoPublisher.test_stop_event_none_runs_indefinitely`, replace the final assertion with:

```python
assert msg is not None
assert msg.content == AUTO_MESSAGE_CONTENT
assert isinstance(msg.timestamp, int)
```

In `TestRunAutoPublisher.test_default_interval_is_300_seconds`, rename the function and update its assertion message:

```python
def test_default_interval_is_360_seconds(self):
    async def _test():
        broker = ProactiveMessageBroker()
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_auto_publisher(broker, stop_event=stop_event)
        )
        result = await broker.poll(timeout_seconds=0.1)
        assert result is None, "should not publish within 360s interval in 0.1s"
        stop_event.set()
        await task

    _run(_test())
```

- [ ] **Step 2: Run the server broker tests and verify they fail**

Run from `WatchingYou-server`:

```bash
pytest tests/test_proactive_messages.py -q
```

Expected: FAIL because `ProactiveMessage` and `now_ms` do not exist yet, and constants still use the 5-minute values.

- [ ] **Step 3: Implement the server broker model**

Edit `WatchingYou-server/app/proactive_messages.py` to match this structure:

```python
import asyncio
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Callable, Optional

# --- Constants ---

AUTO_MESSAGE_INTERVAL_SECONDS = 360
AUTO_MESSAGE_CONTENT = "每隔6min自动发送消息"
POLL_DEFAULT_TIMEOUT_SECONDS = 30
POLL_MIN_TIMEOUT_SECONDS = 1
POLL_MAX_TIMEOUT_SECONDS = 60
MAX_QUEUE_SIZE = 20


# --- Helpers ---

def current_time_millis() -> int:
    return int(time.time() * 1000)


def clamp_poll_timeout(timeout_seconds: Optional[float]) -> float:
    if timeout_seconds is None:
        return POLL_DEFAULT_TIMEOUT_SECONDS
    if timeout_seconds < POLL_MIN_TIMEOUT_SECONDS:
        return POLL_MIN_TIMEOUT_SECONDS
    if timeout_seconds > POLL_MAX_TIMEOUT_SECONDS:
        return POLL_MAX_TIMEOUT_SECONDS
    return timeout_seconds


# --- Models ---

@dataclass(frozen=True)
class ProactiveMessage:
    content: str
    timestamp: int

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


# --- Broker ---

class ProactiveMessageBroker:
    def __init__(
        self,
        max_queue_size: int = MAX_QUEUE_SIZE,
        now_ms: Callable[[], int] = current_time_millis,
    ) -> None:
        self.max_queue_size = max_queue_size
        self._now_ms = now_ms
        self._queue: deque[ProactiveMessage] = deque()
        self._condition = asyncio.Condition()

    async def publish(self, content: str, timestamp_ms: Optional[int] = None) -> None:
        message = ProactiveMessage(
            content=content,
            timestamp=timestamp_ms if timestamp_ms is not None else self._now_ms(),
        )
        async with self._condition:
            if len(self._queue) >= self.max_queue_size:
                self._queue.popleft()  # drop oldest
            self._queue.append(message)
            self._condition.notify_all()

    async def poll(self, timeout_seconds: Optional[float] = None) -> Optional[ProactiveMessage]:
        timeout = clamp_poll_timeout(timeout_seconds)
        async with self._condition:
            if self._queue:
                return self._queue.popleft()

            try:
                await asyncio.wait_for(
                    self._condition.wait(), timeout=timeout
                )
            except asyncio.TimeoutError:
                return None

            # After being notified, check again
            if self._queue:
                return self._queue.popleft()
            return None


# --- Auto publisher ---

async def run_auto_publisher(
    broker: ProactiveMessageBroker,
    interval_seconds: float = AUTO_MESSAGE_INTERVAL_SECONDS,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    while True:
        # Wait for the interval, checking stop_event periodically
        if stop_event is not None:
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=interval_seconds
                )
                # stop_event was set
                return
            except asyncio.TimeoutError:
                pass  # interval elapsed, proceed to publish
        else:
            await asyncio.sleep(interval_seconds)

        await broker.publish(AUTO_MESSAGE_CONTENT)
```

- [ ] **Step 4: Run the server broker tests and verify they pass**

Run from `WatchingYou-server`:

```bash
pytest tests/test_proactive_messages.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the server broker change**

Run from `WatchingYou-server`:

```bash
git add app/proactive_messages.py tests/test_proactive_messages.py
git commit -m "feat: timestamp proactive message queue" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Server `/poll` JSON response

**Files:**
- Modify: `WatchingYou-server/tests/test_main.py`
- Modify: `WatchingYou-server/app/main.py`
- Modify: `WatchingYou-server/README.md`

- [ ] **Step 1: Write failing `/poll` JSON endpoint tests**

Edit `WatchingYou-server/tests/test_main.py`.

Add `import json` near the top:

```python
import json
from unittest.mock import patch
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient
```

Replace `TestPollEndpoint.test_poll_returns_queued_message_when_published` with:

```python
def test_poll_returns_queued_message_when_published(self, client_and_broker):
    client, broker = client_and_broker

    async def _publish():
        await broker.publish("test message", timestamp_ms=123456789)

    asyncio.run(_publish())

    response = client.get("/poll", params={"timeout_seconds": 1})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"content": "test message", "timestamp": 123456789}
```

Replace `TestPollEndpoint.test_poll_default_timeout_when_not_specified` with:

```python
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
```

Replace `TestPollEndpoint.test_poll_returns_queued_message_immediately` with:

```python
def test_poll_returns_queued_message_immediately(self, client_and_broker):
    """When a message is queued before poll, it returns immediately without waiting."""
    client, broker = client_and_broker

    async def _publish():
        await broker.publish("pre-queued", timestamp_ms=333)

    asyncio.run(_publish())

    response = client.get("/poll", params={"timeout_seconds": 5})
    assert response.status_code == 200
    assert response.json() == {"content": "pre-queued", "timestamp": 333}
```

The `import json` is only needed if you choose to inspect raw JSON while debugging. Remove it before committing if it is unused.

- [ ] **Step 2: Run the endpoint tests and verify they fail**

Run from `WatchingYou-server`:

```bash
pytest tests/test_main.py::TestPollEndpoint -q
```

Expected: FAIL because `/poll` still returns `Response(content=message, media_type="text/plain")`.

- [ ] **Step 3: Implement JSON response for `/poll`**

Edit `WatchingYou-server/app/main.py`.

Change the imports:

```python
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
```

Replace the `/poll` handler with:

```python
@app.get("/poll", response_class=Response)
async def poll(timeout_seconds: Optional[float] = Query(default=None)) -> Response:
    message = await proactive_broker.poll(timeout_seconds=timeout_seconds)
    if message is None:
        return Response(status_code=204)
    return JSONResponse(content=message.to_dict())
```

If `json` is unused in `tests/test_main.py`, remove `import json`.

- [ ] **Step 4: Run server endpoint and full server tests**

Run from `WatchingYou-server`:

```bash
pytest tests/test_main.py::TestPollEndpoint -q
pytest -q
```

Expected: both commands PASS.

- [ ] **Step 5: Update server README**

Edit `WatchingYou-server/README.md`.

Replace the `/poll` behavior bullet with:

```markdown
- `GET /poll?timeout_seconds=30` — long-polling endpoint for proactive messages. Returns `200 application/json` with `content` and `timestamp` (Unix epoch milliseconds for when the message was queued) when a proactive message is available, or `204 No Content` when the poll times out without a message. `timeout_seconds` is optional (default 30, clamped to 1–60). The server auto-generates the fixed message `每隔6min自动发送消息` every 6 minutes while running. This is a foreground-only delivery mechanism; no vivo Push, FCM, or background service is involved in this version.
```

Replace the verification paragraph and curl comments for `/poll` with:

```markdown
`/health` prints `Hello from WatchingYou-server`. `/chat` prints the DeepSeek reply (with supervisor persona). `/restart` resets the conversation history. `/poll` returns `200` with a proactive message JSON object when available, or `204` on timeout.

```bash
# Quick poll with a short timeout to see the 204 No Content response quickly
curl -i 'http://127.0.0.1:8000/poll?timeout_seconds=1'
# Long-poll for a proactive message (blocks up to 30 s)
curl http://127.0.0.1:8000/poll
# Wait 6 minutes, then poll again — should return JSON like:
# {"content":"每隔6min自动发送消息","timestamp":1780000000000}
curl http://127.0.0.1:8000/poll
```
```

- [ ] **Step 6: Commit the server endpoint and README change**

Run from `WatchingYou-server`:

```bash
git add app/main.py tests/test_main.py README.md
git commit -m "feat: return proactive poll messages as JSON" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Android API model and JSON parser

**Files:**
- Modify: `WatchingYou-Android-APP/app/build.gradle`
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`

- [ ] **Step 1: Add JSON test dependency**

Edit `WatchingYou-Android-APP/app/build.gradle` and add one test dependency at the end of the dependencies block:

```gradle
testImplementation 'org.json:json:20240303'
```

The dependencies block should include:

```gradle
dependencies {
    implementation 'androidx.room:room-runtime:2.6.1'
    implementation 'androidx.room:room-ktx:2.6.1'
    ksp 'androidx.room:room-compiler:2.6.1'
    implementation 'androidx.recyclerview:recyclerview:1.3.2'
    testImplementation 'junit:junit:4.13.2'
    testImplementation 'org.mockito:mockito-core:5.12.0'
    testImplementation 'org.json:json:20240303'
}
```

- [ ] **Step 2: Write failing Android API tests**

Edit `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`.

Replace `pollProactiveMessageReturnsTextOn200` with:

```kotlin
@Test
fun pollProactiveMessageParsesJsonOn200() {
    server.start(
        responseBody = "{\"content\":\"proactive message\",\"timestamp\":123456789}",
        statusCode = 200
    )

    val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 999L })

    assertEquals(ProactiveMessage("proactive message", 123456789L), result)
    val request = server.takeRequest()
    assertEquals("GET", request.method)
    assertEquals("/poll?timeout_seconds=30", request.path)
}
```

Add this test after it:

```kotlin
@Test
fun pollProactiveMessageFallsBackToPlainTextOnLegacy200() {
    server.start(responseBody = "legacy proactive message", statusCode = 200)

    val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 555L })

    assertEquals(ProactiveMessage("legacy proactive message", 555L), result)
    val request = server.takeRequest()
    assertEquals("GET", request.method)
    assertEquals("/poll?timeout_seconds=30", request.path)
}
```

Add these tests after the legacy plain-text test:

```kotlin
@Test
fun pollProactiveMessageFallsBackToPlainTextWhenJsonFieldsAreMissing() {
    server.start(responseBody = "{\"content\":\"missing timestamp\"}", statusCode = 200)

    val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 777L })

    assertEquals(ProactiveMessage("{\"content\":\"missing timestamp\"}", 777L), result)
}

@Test
fun pollProactiveMessageFallsBackToPlainTextWhenJsonFieldsHaveWrongTypes() {
    server.start(responseBody = "{\"content\":123,\"timestamp\":\"not a number\"}", statusCode = 200)

    val result = WatchingYouApi.pollProactiveMessage(server.baseUrl(), now = { 888L })

    assertEquals(ProactiveMessage("{\"content\":123,\"timestamp\":\"not a number\"}", 888L), result)
}
```

Update `pollProactiveMessageUsesCustomTimeout` to expect a structured message:

```kotlin
@Test
fun pollProactiveMessageUsesCustomTimeout() {
    server.start(
        responseBody = "{\"content\":\"ok\",\"timestamp\":42}",
        statusCode = 200
    )

    val result = WatchingYouApi.pollProactiveMessage(
        server.baseUrl(),
        timeoutSeconds = 15,
        now = { 999L }
    )

    assertEquals(ProactiveMessage("ok", 42L), result)
    val request = server.takeRequest()
    assertEquals("/poll?timeout_seconds=15", request.path)
}
```

Leave `pollProactiveMessageReturnsNullOn204` and `pollProactiveMessageThrowsOn500` in place; they should compile after the implementation changes.

- [ ] **Step 3: Run Android API tests and verify they fail**

Run from `WatchingYou-Android-APP`:

```bash
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.WatchingYouApiTest'
```

Expected: FAIL because `ProactiveMessage` does not exist and `pollProactiveMessage` still returns `String?`.

- [ ] **Step 4: Implement Android API parsing**

Edit `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`.

Add this import:

```kotlin
import org.json.JSONObject
```

Add this data class above `object WatchingYouApi`:

```kotlin
data class ProactiveMessage(
    val content: String,
    val timestamp: Long
)
```

Replace `pollProactiveMessage` with:

```kotlin
fun pollProactiveMessage(
    baseUrl: String,
    timeoutSeconds: Int = 30,
    now: () -> Long = { System.currentTimeMillis() }
): ProactiveMessage? {
    val url = "${baseUrl.trimEnd('/')}/poll?timeout_seconds=$timeoutSeconds"
    val readTimeoutMs = (timeoutSeconds + 5) * 1000
    val (status, body) = requestWithStatus("GET", url, null, readTimeoutMs)
    return when (status) {
        204 -> null
        in 200..299 -> parseProactiveMessage(body, now)
        else -> throw IllegalStateException("HTTP $status: $body")
    }
}

private fun parseProactiveMessage(body: String, now: () -> Long): ProactiveMessage {
    return try {
        val json = JSONObject(body)
        if (!json.has("content") || !json.has("timestamp")) {
            ProactiveMessage(body, now())
        } else {
            val content = json.getString("content")
            val timestamp = json.getLong("timestamp")
            ProactiveMessage(content, timestamp)
        }
    } catch (_: Exception) {
        ProactiveMessage(body, now())
    }
}
```

- [ ] **Step 5: Run Android API tests and verify they pass**

Run from `WatchingYou-Android-APP`:

```bash
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.WatchingYouApiTest'
```

Expected: PASS.

- [ ] **Step 6: Commit the Android API parsing change**

Run from `WatchingYou-Android-APP`:

```bash
git add app/build.gradle app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt
git commit -m "feat: parse proactive poll JSON" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Android coordinator stores server timestamps

**Files:**
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/MainActivity.kt`

- [ ] **Step 1: Update failing coordinator tests**

Edit `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`.

In every `ProactiveMessageSyncCoordinator(...)` construction, remove the `now = { 123L },` argument.

Replace every `pollMessage` lambda that returns a string message with `ProactiveMessage`.

In `successfulPollStoresAiMessageAndCallsOnMessageStored`, use:

```kotlin
pollMessage = { _, _ ->
    val count = pollCount.incrementAndGet()
    if (count == 1) ProactiveMessage("Hello from server", 987654321L) else null
},
```

In that same test, replace the timestamp assertion:

```kotlin
assertEquals(987654321L, inserted.timestamp)
```

In `startWhenAlreadyActiveDoesNothing`, use:

```kotlin
pollMessage = { _, _ ->
    val count = pollCount.incrementAndGet()
    if (count == 1) ProactiveMessage("first message", 222L) else null
},
```

In `emptyPollResultDoesNotInsertMessage`, replace the empty string return with an empty-content structured message so the coordinator preserves its existing no-insert behavior:

```kotlin
pollMessage = { _, _ ->
    pollCount.incrementAndGet()
    ProactiveMessage("", 123L)
},
```

Leave lambdas returning `null`, throwing errors, or blocking with `indefiniteBlocker.await()` as `null` results.

- [ ] **Step 2: Run coordinator tests and verify they fail**

Run from `WatchingYou-Android-APP`:

```bash
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ProactiveMessageSyncCoordinatorTest'
```

Expected: FAIL because the coordinator still expects `(String, Int) -> String?` and still requires `now`.

- [ ] **Step 3: Implement coordinator timestamp storage**

Edit `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`.

Change the constructor dependencies from:

```kotlin
private val pollMessage: (String, Int) -> String?,
private val now: () -> Long,
```

to:

```kotlin
private val pollMessage: (String, Int) -> ProactiveMessage?,
```

Replace the message insertion block with:

```kotlin
if (message != null && message.content.isNotEmpty()) {
    withContext(ioDispatcher) {
        dao.insert(
            Message(
                content = message.content,
                sender = Sender.AI,
                timestamp = message.timestamp
            )
        )
    }
    onMessageStored()
}
```

- [ ] **Step 4: Update MainActivity coordinator construction**

Edit `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/MainActivity.kt`.

Find the `ProactiveMessageSyncCoordinator(` construction near the top of the activity setup. Replace the poll and now arguments with:

```kotlin
pollMessage = { baseUrl, timeoutSeconds ->
    WatchingYouApi.pollProactiveMessage(baseUrl, timeoutSeconds)
},
```

Remove this argument from that constructor call:

```kotlin
now = { System.currentTimeMillis() },
```

Do not remove the other `now = { System.currentTimeMillis() }` usages in chat sending code; those still timestamp user, AI chat, and error messages from immediate chat interactions.

- [ ] **Step 5: Run coordinator tests and compile unit tests**

Run from `WatchingYou-Android-APP`:

```bash
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ProactiveMessageSyncCoordinatorTest'
./gradlew testDebugUnitTest
```

Expected: both commands PASS.

- [ ] **Step 6: Commit the Android coordinator change**

Run from `WatchingYou-Android-APP`:

```bash
git add app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt app/src/main/kotlin/com/example/watchingyou/MainActivity.kt app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt
git commit -m "feat: store proactive server timestamps" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Android time separator threshold tests

**Files:**
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ChatItemTest.kt`

- [ ] **Step 1: Add time separator threshold tests**

Edit `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ChatItemTest.kt`.

Add this test to the class:

```kotlin
@Test
fun messagesToChatItemsInsertsTimeSeparatorWhenGapIsGreaterThanFiveMinutes() {
    val first = Message(
        content = "first",
        sender = Sender.USER,
        timestamp = 1_700_000_000_000L,
        type = MsgType.TEXT
    )
    val second = Message(
        content = "second",
        sender = Sender.AI,
        timestamp = 1_700_000_000_000L + (5 * 60 * 1000L) + 1L,
        type = MsgType.TEXT
    )

    val items = messagesToChatItems(listOf(first, second))

    assertEquals(4, items.size)
    assertEquals(ChatItem.TimeSeparator(first.timestamp), items[0])
    assertTrue(items[1] is ChatItem.UserMessage)
    assertEquals(ChatItem.TimeSeparator(second.timestamp), items[2])
    assertTrue(items[3] is ChatItem.AiMessage)
}
```

Add this test after it:

```kotlin
@Test
fun messagesToChatItemsDoesNotInsertTimeSeparatorWhenGapEqualsFiveMinutes() {
    val first = Message(
        content = "first",
        sender = Sender.USER,
        timestamp = 1_700_000_000_000L,
        type = MsgType.TEXT
    )
    val second = Message(
        content = "second",
        sender = Sender.AI,
        timestamp = 1_700_000_000_000L + (5 * 60 * 1000L),
        type = MsgType.TEXT
    )

    val items = messagesToChatItems(listOf(first, second))

    assertEquals(3, items.size)
    assertEquals(ChatItem.TimeSeparator(first.timestamp), items[0])
    assertTrue(items[1] is ChatItem.UserMessage)
    assertTrue(items[2] is ChatItem.AiMessage)
}
```

- [ ] **Step 2: Run ChatItem tests**

Run from `WatchingYou-Android-APP`:

```bash
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ChatItemTest'
```

Expected: PASS. These tests document existing behavior; implementation changes are not expected.

- [ ] **Step 3: Commit the Android separator tests**

Run from `WatchingYou-Android-APP`:

```bash
git add app/src/test/kotlin/com/example/watchingyou/ChatItemTest.kt
git commit -m "test: document proactive timestamp separators" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Android README update and full verification

**Files:**
- Modify: `WatchingYou-Android-APP/README.md`

- [ ] **Step 1: Update Android README proactive message text**

Edit `WatchingYou-Android-APP/README.md`.

In the feature list, keep the foreground-only behavior text and append timestamp behavior:

```markdown
- 服务端主动消息同步：APP 在前台时通过长轮询（long polling）接收服务端自动生成的主动消息，显示为左侧 AI 消息。服务端返回主动消息入队时间戳，APP 会用该时间戳持久化消息，因此积压消息不会被误认为是当前时间。APP 连接服务端后，`RecyclerView` 顶部会显示 `正在同步服务端数据` 状态提示。仅前台生效，后台、锁屏、APP 被杀死时均不轮询，不支持后台推送（vivo Push / FCM / 后台服务均不在此版本范围内）
```

In the manual verification section, replace steps 4 through 6 with:

```markdown
4. 等待约 6 分钟，确认左侧 AI 消息气泡中出现 `每隔6min自动发送消息`
5. 如果该主动消息与上一条聊天消息间隔超过 5 分钟，确认消息上方显示时间分隔线
6. 按 Home 键将 APP 退到后台，等待约 30 秒，确认不再收到新的主动消息（后台不轮询）
7. 将 APP 切回前台，确认 `正在同步服务端数据` 再次出现，长轮询恢复
```

- [ ] **Step 2: Run full Android tests**

Run from `WatchingYou-Android-APP`:

```bash
./gradlew testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 3: Commit Android README and verification state**

Run from `WatchingYou-Android-APP`:

```bash
git add README.md
git commit -m "docs: update proactive message timestamp behavior" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: End-to-end verification and repository status

**Files:**
- No source changes expected.

- [ ] **Step 1: Run full server tests**

Run from `WatchingYou-server`:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run full Android unit tests**

Run from `WatchingYou-Android-APP`:

```bash
./gradlew testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 3: Check both repository statuses**

Run:

```bash
git -C ~/myworkspace/WatchingYou/WatchingYou-server status --short
git -C ~/myworkspace/WatchingYou/WatchingYou-Android-APP status --short
```

Expected: no output from both commands. If a build tool changed generated files that should not be committed, inspect them before deciding to discard them.

- [ ] **Step 4: Manual smoke test with curl**

Start the server from `WatchingYou-server` in one terminal:

```bash
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another terminal, run:

```bash
curl -i 'http://127.0.0.1:8000/poll?timeout_seconds=1'
```

Expected: `204 No Content` if no message has been queued yet.

Wait at least 6 minutes, then run:

```bash
curl -i 'http://127.0.0.1:8000/poll?timeout_seconds=1'
```

Expected: `200 OK`, `content-type: application/json`, and a body shaped like:

```json
{"content":"每隔6min自动发送消息","timestamp":1780000000000}
```

The exact timestamp value will differ.

- [ ] **Step 5: Manual Android app verification**

Use the existing app flow:

1. Launch the Android app.
2. Register the running server URL.
3. Confirm `正在同步服务端数据` appears.
4. Wait for the proactive message to arrive.
5. Confirm the message text is `每隔6min自动发送消息`.
6. Confirm a time separator appears above it when the server enqueue timestamp is more than 5 minutes after the previous chat message.

If manual Android verification is not possible in the current environment, record that tests passed and manual device verification was skipped.
