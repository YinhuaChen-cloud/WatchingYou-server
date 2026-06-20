# Proactive Message Timestamps Design

## Goal

WatchingYou-server currently queues proactive messages as plain text. WatchingYou-Android-APP stores the time when it receives a queued message, so delayed or accumulated proactive messages look like they were all sent at the current time. The goal is to record the server enqueue time and let Android display that time through its existing chat time separator logic.

This change covers both projects:

- WatchingYou-server publishes one proactive message every 6 minutes.
- The proactive message content is `每隔6min自动发送消息`.
- The server includes the message enqueue timestamp in `/poll` responses.
- WatchingYou-Android-APP stores the server timestamp when present.
- Android keeps compatibility with old plain-text `/poll` responses.

## Server Protocol

`GET /poll` keeps the existing long-polling behavior:

- If no proactive message is available before timeout, return `204 No Content`.
- If a proactive message is available, return `200 application/json`.

The JSON response body is:

```json
{
  "content": "每隔6min自动发送消息",
  "timestamp": 1780000000000
}
```

Fields:

- `content`: message text.
- `timestamp`: Unix epoch milliseconds when the server put the message into the proactive message queue.

The timestamp is not the Android receive time and not the `/poll` response time. It represents the time the message became available on the server.

## Server Internals

`ProactiveMessageBroker` will queue structured proactive message objects instead of raw strings. Each object contains `content` and `timestamp`.

`publish` will support both cases:

- `publish(content)`: fills `timestamp` with the current server time in epoch milliseconds.
- `publish(content, timestamp_ms=...)`: uses the explicit timestamp, primarily for tests and future callers that already know the event time.

Queue behavior remains unchanged:

- FIFO delivery.
- `MAX_QUEUE_SIZE` still limits the queue.
- When full, the broker drops the oldest queued message.
- Waiting pollers are still notified after publish.

The auto publisher changes to:

- `AUTO_MESSAGE_INTERVAL_SECONDS = 360`.
- `AUTO_MESSAGE_CONTENT = "每隔6min自动发送消息"`.
- Publish after each elapsed interval, as it does today, rather than immediately at startup.

## Android API Parsing

Android will represent proactive poll results with a structured model:

```kotlin
data class ProactiveMessage(
    val content: String,
    val timestamp: Long
)
```

`WatchingYouApi.pollProactiveMessage()` will return `ProactiveMessage?` instead of `String?`.

Behavior:

- `204`: return `null`.
- `2xx` with valid JSON object containing string `content` and numeric `timestamp`: return `ProactiveMessage(content, timestamp)`.
- `2xx` with non-JSON body, missing fields, or invalid field types: treat the response as legacy plain text and return `ProactiveMessage(body, now())`.
- Non-2xx responses: keep throwing `IllegalStateException` as today.

The fallback path keeps new Android builds compatible with old WatchingYou-server builds and existing simple test servers.

## Android Storage and Display

`ProactiveMessageSyncCoordinator` will store proactive AI messages using the timestamp supplied by `ProactiveMessage.timestamp`.

For new JSON responses, the stored timestamp is the server enqueue time. For legacy plain-text responses, the stored timestamp is the Android receive time, preserving current behavior.

The existing display pipeline remains responsible for showing time separators:

- `Message.timestamp` is persisted in Room.
- `MessageDao.getAll()` orders by `timestamp ASC, id ASC`.
- `messagesToChatItems()` inserts a `TimeSeparator` before the first message and when the gap between adjacent messages is greater than 5 minutes.
- `ChatAdapter` formats and renders `TimeSeparator` items.

Because queued proactive messages will now be inserted with their server enqueue timestamps, an old proactive message will naturally trigger the existing time separator behavior when its gap from the previous message is greater than 5 minutes.

The current strict `gap > 5 minutes` behavior remains unchanged. A gap exactly equal to 5 minutes does not add a separator; a gap greater than 5 minutes does.

## Error Handling and Compatibility

Server:

- Missing explicit publish timestamp is filled by the server clock.
- `/poll` returns JSON only when a message exists.
- `/poll` timeout behavior stays `204 No Content`.
- Timestamp uses integer epoch milliseconds to avoid time-zone ambiguity.

Android:

- Invalid proactive message JSON does not break sync. It falls back to legacy plain text.
- Empty or null poll results are not inserted.
- HTTP errors and network failures continue through the current retry path: report `RETRYING_AFTER_ERROR`, wait, and do not insert an error chat bubble.

Compatibility:

- New Android + new server: uses structured JSON and accurate enqueue timestamps.
- New Android + old server: reads plain text and uses receive time.
- Old Android + new server: displays the JSON body as plain text. This is acceptable because this work updates both projects together.

## Tests

### Server Tests

Update `tests/test_proactive_messages.py` to cover:

- `AUTO_MESSAGE_INTERVAL_SECONDS == 360`.
- `AUTO_MESSAGE_CONTENT == "每隔6min自动发送消息"`.
- `publish(content)` returns a queued message with matching content and a generated timestamp.
- `publish(content, timestamp_ms=123)` returns a queued message with timestamp `123`.
- FIFO order still works.
- Queue overflow still drops the oldest message.
- The auto publisher emits the new message content and includes a timestamp.

Update `tests/test_main.py` to cover:

- `/poll` with a queued message returns `200` JSON.
- The JSON body contains `content` and `timestamp`.
- `/poll` timeout still returns `204`.

### Android Tests

Update `WatchingYouApiTest.kt` to cover:

- JSON `/poll` response parses into `ProactiveMessage(content, timestamp)`.
- Legacy plain-text `/poll` response falls back to `ProactiveMessage(body, now())`.
- `204` still returns `null`.
- Non-2xx still throws.
- Custom timeout still appears in the request URL.

Update `ProactiveMessageSyncCoordinatorTest.kt` to cover:

- Successful proactive poll stores `message.content` with sender `AI`.
- The inserted `Message.timestamp` is the server-supplied timestamp, not `now()`.
- Null and empty results do not insert messages.
- Exceptions still report retry status and do not insert error bubbles.

Update or extend `ChatItemTest.kt` to cover:

- A gap greater than 5 minutes inserts a `TimeSeparator`.
- A gap exactly equal to 5 minutes does not insert a `TimeSeparator`.

## Manual Verification

1. Start WatchingYou-server.
2. Start WatchingYou-Android-APP and connect it to the server.
3. Wait at least 6 minutes for the server to enqueue `每隔6min自动发送消息`.
4. Bring the Android app to the foreground if needed so it polls `/poll`.
5. Confirm the proactive AI message appears.
6. If the server enqueue time is more than 5 minutes after the previous chat message, confirm Android shows a time separator above the proactive message.
7. Confirm old accumulated messages no longer all appear as if they were sent at the Android receive time.

## Out of Scope

- Background push notifications.
- FCM, vivo Push, or Android background services.
- Changing the existing 5-minute separator threshold.
- Supporting old Android clients against the new JSON server protocol beyond accepting that they may display JSON as text.
