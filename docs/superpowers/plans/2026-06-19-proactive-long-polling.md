# Proactive Long Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a foreground-only proactive message path where `WatchingYou-server` generates `每隔5min自动发的消息` every 5 minutes and `WatchingYou-Android-APP` receives it through long polling while the chat screen is open.

**Architecture:** The server gets a focused in-memory proactive message broker and a `GET /poll` endpoint. The Android app gets a focused foreground sync coordinator that loops over `/poll`, stores returned messages as `Sender.AI`, and updates a small syncing status row in `MainActivity`.

**Tech Stack:** Python 3, FastAPI, asyncio, pytest, Kotlin, Android XML layouts, Room, coroutines, JUnit.

---

## Repositories and Commit Boundaries

This feature spans two sibling git repositories:

- Server repo: `~/myworkspace/WatchingYou/WatchingYou-server`
- Android repo: `~/myworkspace/WatchingYou/WatchingYou-Android-APP`

Commit server changes inside `WatchingYou-server`. Commit Android changes inside `WatchingYou-Android-APP`. Do not run git commands from `~/myworkspace/WatchingYou` because it is not a git repository.

## File Structure

### Server files

- Create: `WatchingYou-server/app/proactive_messages.py`
  - Owns the in-memory queue, long-poll waiting, timeout clamping, and auto-publisher loop.
- Create: `WatchingYou-server/tests/test_proactive_messages.py`
  - Unit-tests broker behavior without FastAPI.
- Modify: `WatchingYou-server/app/main.py`
  - Wires FastAPI lifespan startup/shutdown to the broker.
  - Adds `GET /poll`.
  - Keeps `/health` and `/chat` behavior unchanged.
- Modify: `WatchingYou-server/tests/test_main.py`
  - Adds endpoint tests for `/poll`.

### Android files

- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`
  - Adds `pollProactiveMessage(baseUrl, timeoutSeconds)`.
  - Allows the internal request helper to handle `204 No Content`.
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`
  - Tests `/poll` success, `204`, and server error behavior.
- Create: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`
  - Owns the foreground polling loop and status callbacks.
- Create: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`
  - Tests coordinator behavior independent of `MainActivity`.
- Modify: `WatchingYou-Android-APP/app/src/main/res/layout/activity_main.xml`
  - Adds sync status row below the top bar.
- Modify: `WatchingYou-Android-APP/app/src/main/res/values/strings.xml`
  - Adds sync status strings.
- Modify: `WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ServerRegistrationUiResourcesTest.kt`
  - Verifies new UI resources exist.
- Modify: `WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/MainActivity.kt`
  - Starts/stops proactive sync from foreground lifecycle.
  - Updates sync status UI.
  - Restarts sync after successful server registration.

---

## Task 1: Add the Server Proactive Message Broker

**Files:**
- Create: `~/myworkspace/WatchingYou/WatchingYou-server/tests/test_proactive_messages.py`
- Create: `~/myworkspace/WatchingYou/WatchingYou-server/app/proactive_messages.py`

- [ ] **Step 1: Write failing broker tests**

Create `~/myworkspace/WatchingYou/WatchingYou-server/tests/test_proactive_messages.py`:

```python
import asyncio

import pytest

from app.proactive_messages import (
    AUTO_MESSAGE_CONTENT,
    ProactiveMessageBroker,
    clamp_poll_timeout,
    run_auto_publisher,
)


@pytest.mark.asyncio
async def test_poll_returns_queued_message_immediately():
    broker = ProactiveMessageBroker()
    await broker.publish("hello")

    message = await broker.poll(timeout_seconds=1)

    assert message == "hello"


@pytest.mark.asyncio
async def test_poll_returns_none_after_timeout_when_no_message_arrives():
    broker = ProactiveMessageBroker()

    message = await broker.poll(timeout_seconds=0.01)

    assert message is None


@pytest.mark.asyncio
async def test_poll_waits_until_publish_wakes_it():
    broker = ProactiveMessageBroker()

    async def publish_later():
        await asyncio.sleep(0.01)
        await broker.publish("wake up")

    publisher = asyncio.create_task(publish_later())
    message = await broker.poll(timeout_seconds=1)
    await publisher

    assert message == "wake up"


@pytest.mark.asyncio
async def test_queue_drops_oldest_message_when_full():
    broker = ProactiveMessageBroker(max_queue_size=2)

    await broker.publish("first")
    await broker.publish("second")
    await broker.publish("third")

    assert await broker.poll(timeout_seconds=0.01) == "second"
    assert await broker.poll(timeout_seconds=0.01) == "third"
    assert await broker.poll(timeout_seconds=0.01) is None


def test_clamp_poll_timeout_uses_bounds_and_default():
    assert clamp_poll_timeout(None) == 30
    assert clamp_poll_timeout(-1) == 1
    assert clamp_poll_timeout(0) == 1
    assert clamp_poll_timeout(10) == 10
    assert clamp_poll_timeout(999) == 60


@pytest.mark.asyncio
async def test_auto_publisher_publishes_fixed_message_after_interval():
    broker = ProactiveMessageBroker()
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_auto_publisher(
            broker,
            interval_seconds=0.01,
            stop_event=stop_event,
        )
    )

    message = await broker.poll(timeout_seconds=1)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1)

    assert message == AUTO_MESSAGE_CONTENT
```

- [ ] **Step 2: Run broker tests and verify they fail**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
pytest tests/test_proactive_messages.py -v
```

Expected: FAIL with an import error because `app.proactive_messages` does not exist.

- [ ] **Step 3: Implement the broker**

Create `~/myworkspace/WatchingYou/WatchingYou-server/app/proactive_messages.py`:

```python
import asyncio
from collections import deque
from contextlib import suppress
from typing import Deque, Optional

AUTO_MESSAGE_INTERVAL_SECONDS = 300
AUTO_MESSAGE_CONTENT = "每隔5min自动发的消息"
POLL_DEFAULT_TIMEOUT_SECONDS = 30
POLL_MIN_TIMEOUT_SECONDS = 1
POLL_MAX_TIMEOUT_SECONDS = 60
MAX_QUEUE_SIZE = 20


def clamp_poll_timeout(timeout_seconds: Optional[float]) -> float:
    if timeout_seconds is None:
        return POLL_DEFAULT_TIMEOUT_SECONDS
    return min(max(timeout_seconds, POLL_MIN_TIMEOUT_SECONDS), POLL_MAX_TIMEOUT_SECONDS)


class ProactiveMessageBroker:
    def __init__(self, max_queue_size: int = MAX_QUEUE_SIZE):
        self._max_queue_size = max_queue_size
        self._queue: Deque[str] = deque()
        self._condition = asyncio.Condition()

    async def publish(self, content: str) -> None:
        async with self._condition:
            if len(self._queue) >= self._max_queue_size:
                self._queue.popleft()
            self._queue.append(content)
            self._condition.notify()

    async def poll(self, timeout_seconds: Optional[float] = None) -> Optional[str]:
        timeout = clamp_poll_timeout(timeout_seconds)
        async with self._condition:
            if self._queue:
                return self._queue.popleft()

            try:
                await asyncio.wait_for(self._condition.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return None

            if self._queue:
                return self._queue.popleft()
            return None


async def run_auto_publisher(
    broker: ProactiveMessageBroker,
    interval_seconds: float = AUTO_MESSAGE_INTERVAL_SECONDS,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        if stop.is_set():
            break
        await broker.publish(AUTO_MESSAGE_CONTENT)
```

- [ ] **Step 4: Run broker tests and verify they pass**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
pytest tests/test_proactive_messages.py -v
```

Expected: all tests in `tests/test_proactive_messages.py` PASS.

- [ ] **Step 5: Commit server broker changes**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
git add app/proactive_messages.py tests/test_proactive_messages.py
git commit -m "feat: add proactive message broker"
```

---

## Task 2: Add Server `GET /poll` and Lifespan Wiring

**Files:**
- Modify: `~/myworkspace/WatchingYou/WatchingYou-server/app/main.py`
- Modify: `~/myworkspace/WatchingYou/WatchingYou-server/tests/test_main.py`

- [ ] **Step 1: Add failing `/poll` endpoint tests**

Append these tests to `~/myworkspace/WatchingYou/WatchingYou-server/tests/test_main.py`:

```python

def test_poll_returns_queued_proactive_message(client):
    import app.main

    async def publish_message():
        await app.main.proactive_broker.publish("server says hi")

    import anyio
    anyio.run(publish_message)

    response = client.get("/poll?timeout_seconds=1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "server says hi"


def test_poll_returns_204_when_no_message_arrives(client):
    response = client.get("/poll?timeout_seconds=0.01")

    assert response.status_code == 204
    assert response.text == ""
```

- [ ] **Step 2: Run endpoint tests and verify they fail**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
pytest tests/test_main.py::test_poll_returns_queued_proactive_message tests/test_main.py::test_poll_returns_204_when_no_message_arrives -v
```

Expected: FAIL because `GET /poll` does not exist or `app.main.proactive_broker` has not been added yet.

- [ ] **Step 3: Wire broker and `/poll` into FastAPI**

Modify `~/myworkspace/WatchingYou/WatchingYou-server/app/main.py` so it has this full content:

```python
import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import load_config
from app import deepseek
from app.proactive_messages import ProactiveMessageBroker, run_auto_publisher

GREETING = "Hello from WatchingYou-server"

_config = load_config()
_api_key = _config["deepseek_api_key"]

proactive_broker = ProactiveMessageBroker()
_auto_publisher_stop = asyncio.Event()
_auto_publisher_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _auto_publisher_stop, _auto_publisher_task
    _auto_publisher_stop = asyncio.Event()
    _auto_publisher_task = asyncio.create_task(
        run_auto_publisher(proactive_broker, stop_event=_auto_publisher_stop)
    )
    try:
        yield
    finally:
        _auto_publisher_stop.set()
        if _auto_publisher_task is not None:
            await _auto_publisher_task
            _auto_publisher_task = None


app = FastAPI(title="WatchingYou Server", lifespan=lifespan)


@app.get("/health", response_class=Response)
def health() -> Response:
    return Response(content=GREETING, media_type="text/plain")


@app.get("/poll", response_class=Response)
async def poll(timeout_seconds: float | None = None) -> Response:
    message = await proactive_broker.poll(timeout_seconds=timeout_seconds)
    if message is None:
        return Response(status_code=204)
    return Response(content=message, media_type="text/plain")


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

- [ ] **Step 4: Run `/poll` endpoint tests and verify they pass**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
pytest tests/test_main.py::test_poll_returns_queued_proactive_message tests/test_main.py::test_poll_returns_204_when_no_message_arrives -v
```

Expected: both selected tests PASS.

- [ ] **Step 5: Run full server test suite**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
pytest -v
```

Expected: all server tests PASS.

- [ ] **Step 6: Commit server endpoint changes**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
git add app/main.py tests/test_main.py
git commit -m "feat: expose proactive message polling endpoint"
```

---

## Task 3: Add Android `/poll` API Client Support

**Files:**
- Modify: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`
- Modify: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt`

- [ ] **Step 1: Add failing API tests**

In `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt`, add imports:

```kotlin
import org.junit.Assert.assertNull
import org.junit.Assert.fail
```

Add these tests before the `private class TestHttpServer` block:

```kotlin
    @Test
    fun pollProactiveMessageReturnsBodyFor200Response() {
        server.start(responseBody = "每隔5min自动发的消息")

        val response = WatchingYouApi.pollProactiveMessage(server.baseUrl(), timeoutSeconds = 7)

        assertEquals("每隔5min自动发的消息", response)
        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/poll?timeout_seconds=7", request.path)
    }

    @Test
    fun pollProactiveMessageReturnsNullFor204Response() {
        server.start(responseCode = 204, responseBody = "")

        val response = WatchingYouApi.pollProactiveMessage(server.baseUrl(), timeoutSeconds = 7)

        assertNull(response)
        assertEquals("/poll?timeout_seconds=7", server.takeRequest().path)
    }

    @Test
    fun pollProactiveMessageThrowsForServerError() {
        server.start(responseCode = 500, responseBody = "boom")

        try {
            WatchingYouApi.pollProactiveMessage(server.baseUrl(), timeoutSeconds = 7)
            fail("Expected server error to throw")
        } catch (e: IllegalStateException) {
            assertTrue(e.message.orEmpty().contains("HTTP 500"))
            assertTrue(e.message.orEmpty().contains("boom"))
        }
    }
```

Update the `TestHttpServer.start` and `handle` methods in the same file to accept response codes:

```kotlin
        fun start(responseBody: String, responseCode: Int = 200) {
            worker = thread(start = true) {
                started.countDown()
                serverSocket.accept().use { socket -> handle(socket, responseCode, responseBody) }
            }
            assertTrue("server did not start", started.await(2, TimeUnit.SECONDS))
        }
```

```kotlin
        private fun handle(socket: Socket, responseCode: Int, responseBody: String) {
            val reader = BufferedReader(InputStreamReader(socket.getInputStream(), Charsets.UTF_8))
            val requestLine = reader.readLine()
            val parts = requestLine.split(" ")
            val headers = mutableMapOf<String, String>()
            while (true) {
                val line = reader.readLine()
                if (line.isEmpty()) break
                val separator = line.indexOf(':')
                if (separator > 0) {
                    headers[line.substring(0, separator).lowercase()] = line.substring(separator + 1).trim()
                }
            }
            val contentLength = headers["content-length"]?.toIntOrNull() ?: 0
            val bodyChars = CharArray(contentLength)
            var read = 0
            while (read < contentLength) {
                val count = reader.read(bodyChars, read, contentLength - read)
                if (count == -1) break
                read += count
            }
            requests.add(RecordedRequest(parts[0], parts[1], String(bodyChars, 0, read)))

            val bytes = responseBody.toByteArray(Charsets.UTF_8)
            val reason = if (responseCode == 204) "No Content" else if (responseCode == 200) "OK" else "Error"
            val response = "HTTP/1.1 $responseCode $reason\r\n" +
                "Content-Type: text/plain; charset=utf-8\r\n" +
                "Content-Length: ${bytes.size}\r\n" +
                "Connection: close\r\n" +
                "\r\n"
            socket.getOutputStream().write(response.toByteArray(Charsets.UTF_8))
            socket.getOutputStream().write(bytes)
            socket.getOutputStream().flush()
        }
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.WatchingYouApiTest'
```

Expected: FAIL because `WatchingYouApi.pollProactiveMessage` does not exist.

- [ ] **Step 3: Implement `/poll` API support**

Modify `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt` to this full content:

```kotlin
package com.example.watchingyou

import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

object WatchingYouApi {
    const val EXPECTED_GREETING = "Hello from WatchingYou-server"

    data class TestResult(val body: String, val latencyMs: Long)

    fun isExpectedGreeting(body: String): Boolean = body == EXPECTED_GREETING

    fun testServer(
        baseUrl: String,
        elapsedRealtime: () -> Long = { System.nanoTime() / 1_000_000L }
    ): TestResult {
        val start = elapsedRealtime()
        val body = request("GET", endpointUrl(baseUrl, "health"), null).body
        return TestResult(body = body, latencyMs = elapsedRealtime() - start)
    }

    fun sendChat(baseUrl: String, message: String? = null): String {
        return request("POST", endpointUrl(baseUrl, "chat"), message).body
    }

    fun pollProactiveMessage(baseUrl: String, timeoutSeconds: Int = 30): String? {
        val response = request(
            method = "GET",
            url = "${endpointUrl(baseUrl, "poll")}?timeout_seconds=$timeoutSeconds",
            body = null,
            readTimeoutMs = (timeoutSeconds + 5) * 1000
        )
        return if (response.statusCode == 204) null else response.body
    }

    private fun endpointUrl(baseUrl: String, endpoint: String): String {
        return "${baseUrl.trimEnd('/')}/$endpoint"
    }

    private fun request(
        method: String,
        url: String,
        body: String?,
        readTimeoutMs: Int = 5000
    ): HttpResponse {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 5000
        connection.readTimeout = readTimeoutMs

        if (body != null) {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "text/plain; charset=utf-8")
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                writer.write(body)
            }
        }

        return try {
            val responseCode = connection.responseCode
            val stream = if (responseCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }
            val responseBody = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (responseCode !in 200..299) {
                throw IllegalStateException("HTTP $responseCode: $responseBody")
            }
            HttpResponse(responseCode, responseBody)
        } finally {
            connection.disconnect()
        }
    }

    private data class HttpResponse(val statusCode: Int, val body: String)
}
```

- [ ] **Step 4: Run API tests and verify they pass**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.WatchingYouApiTest'
```

Expected: `WatchingYouApiTest` PASS.

- [ ] **Step 5: Commit Android API changes**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
git add app/src/main/kotlin/com/example/watchingyou/WatchingYouApi.kt app/src/test/kotlin/com/example/watchingyou/WatchingYouApiTest.kt
git commit -m "feat: add proactive message polling API"
```

---

## Task 4: Add Android Proactive Sync Coordinator

**Files:**
- Create: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`
- Create: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`

- [ ] **Step 1: Write failing coordinator tests**

Create `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt`:

```kotlin
package com.example.watchingyou

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProactiveMessageSyncCoordinatorTest {
    @Test
    fun startWithoutRegisteredServerReportsUnregisteredAndDoesNotPoll() = runBlocking {
        var pollCount = 0
        val statuses = mutableListOf<ProactiveSyncStatus>()
        val coordinator = ProactiveMessageSyncCoordinator(
            dao = RecordingChatMessageDao(),
            appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
            ioDispatcher = Dispatchers.Default,
            baseUrlProvider = { null },
            pollMessage = { _, _ ->
                pollCount += 1
                "message"
            },
            now = { 123L },
            onStatusChanged = { statuses += it },
            onMessageStored = {},
            retryDelayMs = 1
        )

        coordinator.start()
        coordinator.stop()

        assertEquals(listOf(ProactiveSyncStatus.UNREGISTERED), statuses)
        assertEquals(0, pollCount)
    }

    @Test
    fun successfulPollStoresAiMessageAndNotifiesUi() = runBlocking {
        val dao = RecordingChatMessageDao()
        val stored = CountDownLatch(1)
        val never = CompletableDeferred<String?>()
        var pollCount = 0
        val coordinatorScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val coordinator = ProactiveMessageSyncCoordinator(
            dao = dao,
            appScope = coordinatorScope,
            ioDispatcher = Dispatchers.Default,
            baseUrlProvider = { "http://server" },
            pollMessage = { _, _ ->
                if (pollCount++ == 0) "每隔5min自动发的消息" else runBlocking { never.await() }
            },
            now = { 456L },
            onStatusChanged = {},
            onMessageStored = { stored.countDown() },
            retryDelayMs = 1
        )

        coordinator.start()
        assertTrue("message was not stored", stored.await(2, TimeUnit.SECONDS))
        coordinator.stop()
        coordinatorScope.cancel()

        assertEquals(1, dao.inserted.size)
        assertEquals("每隔5min自动发的消息", dao.inserted[0].content)
        assertEquals(Sender.AI, dao.inserted[0].sender)
        assertEquals(456L, dao.inserted[0].timestamp)
    }

    @Test
    fun pollFailureReportsRetryAndDoesNotInsertErrorMessage() = runBlocking {
        val dao = RecordingChatMessageDao()
        val retryReported = CountDownLatch(1)
        val coordinatorScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val coordinator = ProactiveMessageSyncCoordinator(
            dao = dao,
            appScope = coordinatorScope,
            ioDispatcher = Dispatchers.Default,
            baseUrlProvider = { "http://server" },
            pollMessage = { _, _ -> error("network down") },
            now = { 789L },
            onStatusChanged = {
                if (it == ProactiveSyncStatus.RETRYING_AFTER_ERROR) retryReported.countDown()
            },
            onMessageStored = {},
            retryDelayMs = 100
        )

        coordinator.start()
        assertTrue("retry status was not reported", retryReported.await(2, TimeUnit.SECONDS))
        coordinator.stop()
        coordinatorScope.cancel()

        assertTrue(dao.inserted.none { it.sender == Sender.ERROR })
    }

    private class RecordingChatMessageDao : ChatMessageDao {
        val inserted = mutableListOf<Message>()

        override suspend fun insert(message: Message): Long {
            inserted += message.copy(id = inserted.size + 1L)
            return inserted.size.toLong()
        }

        override suspend fun getAll(): List<Message> = inserted.toList()
    }
}
```

- [ ] **Step 2: Run coordinator tests and verify they fail**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ProactiveMessageSyncCoordinatorTest'
```

Expected: FAIL because `ProactiveMessageSyncCoordinator` and `ProactiveSyncStatus` do not exist.

- [ ] **Step 3: Implement coordinator**

Create `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt`:

```kotlin
package com.example.watchingyou

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private const val DEFAULT_POLL_TIMEOUT_SECONDS = 30
private const val DEFAULT_RETRY_DELAY_MS = 5_000L

enum class ProactiveSyncStatus {
    UNREGISTERED,
    SYNCING,
    RETRYING_AFTER_ERROR,
    STOPPED
}

class ProactiveMessageSyncCoordinator(
    private val dao: ChatMessageDao,
    private val appScope: CoroutineScope,
    private val ioDispatcher: CoroutineDispatcher,
    private val baseUrlProvider: () -> String?,
    private val pollMessage: (String, Int) -> String?,
    private val now: () -> Long,
    private val onStatusChanged: (ProactiveSyncStatus) -> Unit,
    private val onMessageStored: () -> Unit,
    private val retryDelayMs: Long = DEFAULT_RETRY_DELAY_MS
) {
    private var activeJob: Job? = null

    @Synchronized
    fun start() {
        if (activeJob?.isActive == true) return
        val baseUrl = baseUrlProvider()
        if (baseUrl == null) {
            onStatusChanged(ProactiveSyncStatus.UNREGISTERED)
            return
        }

        activeJob = appScope.launch {
            while (isActive) {
                onStatusChanged(ProactiveSyncStatus.SYNCING)
                try {
                    val message = withContext(ioDispatcher) {
                        pollMessage(baseUrl, DEFAULT_POLL_TIMEOUT_SECONDS)
                    }
                    if (!message.isNullOrEmpty()) {
                        withContext(ioDispatcher) {
                            dao.insert(
                                Message(
                                    content = message,
                                    sender = Sender.AI,
                                    timestamp = now()
                                )
                            )
                        }
                        onMessageStored()
                    }
                } catch (e: Exception) {
                    onStatusChanged(ProactiveSyncStatus.RETRYING_AFTER_ERROR)
                    delay(retryDelayMs)
                }
            }
        }
    }

    @Synchronized
    fun stop() {
        activeJob?.cancel()
        activeJob = null
        onStatusChanged(ProactiveSyncStatus.STOPPED)
    }

    @Synchronized
    fun restart() {
        stop()
        start()
    }
}
```

- [ ] **Step 4: Run coordinator tests and verify they pass**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ProactiveMessageSyncCoordinatorTest'
```

Expected: `ProactiveMessageSyncCoordinatorTest` PASS.

- [ ] **Step 5: Commit coordinator changes**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
git add app/src/main/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinator.kt app/src/test/kotlin/com/example/watchingyou/ProactiveMessageSyncCoordinatorTest.kt
git commit -m "feat: add proactive message sync coordinator"
```

---

## Task 5: Add Android Sync Status UI Resources

**Files:**
- Modify: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/res/layout/activity_main.xml`
- Modify: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/res/values/strings.xml`
- Modify: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ServerRegistrationUiResourcesTest.kt`

- [ ] **Step 1: Add failing resource assertions**

In `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/test/kotlin/com/example/watchingyou/ServerRegistrationUiResourcesTest.kt`, add these assertions inside `exposesServerRegistrationUiResources()`:

```kotlin
        assertNotEquals(0, R.id.sync_status_row)
        assertNotEquals(0, R.id.progress_sync)
        assertNotEquals(0, R.id.tv_sync_status)
        assertNotEquals(0, R.string.syncing_server_data)
        assertNotEquals(0, R.string.sync_server_failed_retrying)
        assertNotEquals(0, R.string.register_server_first)
```

- [ ] **Step 2: Run resource test and verify it fails**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ServerRegistrationUiResourcesTest'
```

Expected: FAIL because the new IDs and strings do not exist.

- [ ] **Step 3: Add strings**

Modify `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/res/values/strings.xml` to this full content:

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">WatchingYou</string>
    <string name="send">发送</string>
    <string name="input_hint">输入消息…</string>
    <string name="server">服务端</string>
    <string name="register_server">注册服务端公网IP:PORT</string>
    <string name="server_address_hint">公网 IP:PORT 或 URL</string>
    <string name="server_address_example">http://1.2.3.4:8000</string>
    <string name="test">测试</string>
    <string name="save_and_register">保存并注册</string>
    <string name="test_not_run">状态：未测试</string>
    <string name="syncing_server_data">正在同步服务端数据</string>
    <string name="sync_server_failed_retrying">服务端同步失败，稍后重试</string>
    <string name="register_server_first">请先注册服务端</string>
</resources>
```

- [ ] **Step 4: Add sync status row to layout**

In `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/res/layout/activity_main.xml`, insert this block after the top bar `LinearLayout` ending at line 35 and before the `RecyclerView`:

```xml
    <LinearLayout
        android:id="@+id/sync_status_row"
        android:layout_width="match_parent"
        android:layout_height="32dp"
        android:orientation="horizontal"
        android:gravity="center_vertical"
        android:paddingStart="16dp"
        android:paddingEnd="16dp"
        android:background="#F7F7F7">

        <ProgressBar
            android:id="@+id/progress_sync"
            style="?android:attr/progressBarStyleSmall"
            android:layout_width="20dp"
            android:layout_height="20dp"
            android:indeterminate="true" />

        <TextView
            android:id="@+id/tv_sync_status"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:layout_marginStart="8dp"
            android:text="@string/register_server_first"
            android:textColor="#666666"
            android:textSize="13sp" />

    </LinearLayout>
```

- [ ] **Step 5: Run resource test and verify it passes**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest --tests 'com.example.watchingyou.ServerRegistrationUiResourcesTest'
```

Expected: `ServerRegistrationUiResourcesTest` PASS.

- [ ] **Step 6: Commit UI resource changes**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
git add app/src/main/res/layout/activity_main.xml app/src/main/res/values/strings.xml app/src/test/kotlin/com/example/watchingyou/ServerRegistrationUiResourcesTest.kt
git commit -m "feat: add proactive sync status UI"
```

---

## Task 6: Wire Android Foreground Lifecycle to Proactive Sync

**Files:**
- Modify: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/MainActivity.kt`

- [ ] **Step 1: Add MainActivity fields**

In `~/myworkspace/WatchingYou/WatchingYou-Android-APP/app/src/main/kotlin/com/example/watchingyou/MainActivity.kt`, add imports:

```kotlin
import android.view.View
import android.widget.ProgressBar
```

Add fields near the existing UI fields:

```kotlin
    private lateinit var syncStatusRow: View
    private lateinit var progressSync: ProgressBar
    private lateinit var tvSyncStatus: TextView
    private lateinit var proactiveSyncCoordinator: ProactiveMessageSyncCoordinator
```

- [ ] **Step 2: Initialize UI and coordinator in `onCreate`**

After existing `findViewById` calls for `btnServer`, add:

```kotlin
        syncStatusRow = findViewById(R.id.sync_status_row)
        progressSync = findViewById(R.id.progress_sync)
        tvSyncStatus = findViewById(R.id.tv_sync_status)
```

After `chatSendCoordinator = ChatSendCoordinator.getInstance(applicationContext, messageDao)`, add:

```kotlin
        proactiveSyncCoordinator = ProactiveMessageSyncCoordinator(
            dao = messageDao,
            appScope = activityScope,
            ioDispatcher = Dispatchers.IO,
            baseUrlProvider = { ServerConfig.getBaseUrl(applicationContext) },
            pollMessage = WatchingYouApi::pollProactiveMessage,
            now = { System.currentTimeMillis() },
            onStatusChanged = { status -> updateProactiveSyncStatus(status) },
            onMessageStored = { activityScope.launch { refreshMessages() } }
        )
```

- [ ] **Step 3: Add lifecycle methods**

Add these methods inside `MainActivity`:

```kotlin
    override fun onStart() {
        super.onStart()
        proactiveSyncCoordinator.start()
    }

    override fun onStop() {
        proactiveSyncCoordinator.stop()
        super.onStop()
    }
```

- [ ] **Step 4: Restart sync after successful registration**

In `registerServerAddress`, inside the `if (registrationResult == null)` branch, change it to:

```kotlin
            if (registrationResult == null) {
                dialogRef.get()?.dismiss()
                proactiveSyncCoordinator.restart()
            } else if (dialogRef.get()?.isShowing == true) {
                resultViewRef.get()?.text = registrationResult
            }
```

- [ ] **Step 5: Add sync status UI update method**

Add this method inside `MainActivity`:

```kotlin
    private fun updateProactiveSyncStatus(status: ProactiveSyncStatus) {
        if (destroyed) return
        when (status) {
            ProactiveSyncStatus.UNREGISTERED -> {
                syncStatusRow.visibility = View.VISIBLE
                progressSync.visibility = View.GONE
                tvSyncStatus.setText(R.string.register_server_first)
            }
            ProactiveSyncStatus.SYNCING -> {
                syncStatusRow.visibility = View.VISIBLE
                progressSync.visibility = View.VISIBLE
                tvSyncStatus.setText(R.string.syncing_server_data)
            }
            ProactiveSyncStatus.RETRYING_AFTER_ERROR -> {
                syncStatusRow.visibility = View.VISIBLE
                progressSync.visibility = View.GONE
                tvSyncStatus.setText(R.string.sync_server_failed_retrying)
            }
            ProactiveSyncStatus.STOPPED -> {
                syncStatusRow.visibility = View.GONE
                progressSync.visibility = View.GONE
            }
        }
    }
```

- [ ] **Step 6: Build Android app**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew assembleDebug
```

Expected: build succeeds and produces `app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Step 7: Run Android unit tests**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest
```

Expected: all Android unit tests PASS.

- [ ] **Step 8: Commit Android lifecycle wiring**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
git add app/src/main/kotlin/com/example/watchingyou/MainActivity.kt
git commit -m "feat: sync proactive messages while app is foregrounded"
```

---

## Task 7: End-to-End Verification and Documentation

**Files:**
- Modify: `~/myworkspace/WatchingYou/WatchingYou-server/README.md`
- Modify: `~/myworkspace/WatchingYou/WatchingYou-Android-APP/README.md`

- [ ] **Step 1: Update server README behavior section**

In `~/myworkspace/WatchingYou/WatchingYou-server/README.md`, update the behavior list to include:

```markdown
- `GET /poll?timeout_seconds=30` — long-polls for proactive server messages. Returns `200 text/plain` with a message when one is available, or `204 No Content` when no message arrives before timeout. The first proactive message version is generated every 5 minutes with the content `每隔5min自动发的消息`.
```

Update the verify block to include:

```bash
curl -i 'http://127.0.0.1:8000/poll?timeout_seconds=1'
```

- [ ] **Step 2: Update Android README feature list**

In `~/myworkspace/WatchingYou/WatchingYou-Android-APP/README.md`, add these bullets under `## 功能`:

```markdown
- APP 前台运行时，会通过长轮询同步服务端主动消息
- 同步服务端主动消息时，会显示 `正在同步服务端数据`
- 当前基础版只保证 APP 打开时同步主动消息；后台、锁屏、APP 被系统杀掉后的可靠通知需要后续接入 vivo 厂商推送
```

- [ ] **Step 3: Run all server tests**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
pytest -v
```

Expected: all server tests PASS.

- [ ] **Step 4: Run all Android unit tests**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew testDebugUnitTest
```

Expected: all Android unit tests PASS.

- [ ] **Step 5: Build Android debug APK**

Run:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
./gradlew assembleDebug
```

Expected: build succeeds and produces `app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Step 6: Manual server verification**

Run the server:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another terminal, verify a short empty poll:

```bash
curl -i 'http://127.0.0.1:8000/poll?timeout_seconds=1'
```

Expected:

```text
HTTP/1.1 204 No Content
```

- [ ] **Step 7: Manual Android verification**

Install and open the debug APK on the vivo phone or test device. Then:

1. Register the running server address in the app.
2. Confirm the chat screen shows `正在同步服务端数据` with a small spinner.
3. Keep the app open for about 5 minutes.
4. Confirm a left-side AI message appears with exactly this content:

```text
每隔5min自动发的消息
```

5. Press Home to background the app.
6. Confirm from server logs that polling stops after the in-flight `/poll` is cancelled or times out.
7. Reopen the app.
8. Confirm `正在同步服务端数据` appears again and polling resumes.

- [ ] **Step 8: Commit documentation changes**

Commit server docs:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-server
git add README.md docs/superpowers/specs/2026-06-19-proactive-long-polling-design.md docs/superpowers/plans/2026-06-19-proactive-long-polling.md
git commit -m "docs: document proactive long polling design"
```

Commit Android docs:

```bash
cd ~/myworkspace/WatchingYou/WatchingYou-Android-APP
git add README.md
git commit -m "docs: document foreground proactive sync"
```

---

## Final Verification Checklist

- [ ] `WatchingYou-server`: `pytest -v` passes.
- [ ] `WatchingYou-Android-APP`: `./gradlew testDebugUnitTest` passes.
- [ ] `WatchingYou-Android-APP`: `./gradlew assembleDebug` succeeds.
- [ ] `GET /health` still returns `Hello from WatchingYou-server`.
- [ ] `POST /chat` still proxies to DeepSeek and `/restart` still resets history.
- [ ] `GET /poll?timeout_seconds=1` returns `204` when no proactive message is queued.
- [ ] Android shows `请先注册服务端` before server registration.
- [ ] Android shows `正在同步服务端数据` with a small spinner after server registration.
- [ ] Android stores proactive messages as `Sender.AI`, not `Sender.ERROR`.
- [ ] Android does not create chat error bubbles for proactive sync failures.
- [ ] Foreground sync stops when the Activity stops and restarts when it starts again.
