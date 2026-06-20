# Proactive Long Polling Design

## Overview

This change adds a foreground-only proactive message sync path between `WatchingYou-server` and `WatchingYou-Android-APP`.

The first version intentionally does not use vivo Push, Firebase, background services, user accounts, or server-side persistence. It verifies the core product behavior: the server can generate a message on its own schedule, and the Android app can receive and display that message while the chat screen is open.

The automatic message content is fixed for this version:

```text
每隔5min自动发的消息
```

## Goals

- `WatchingYou-server` generates the fixed message every 5 minutes.
- `WatchingYou-Android-APP` receives proactive messages using long polling while the chat screen is in the foreground.
- Received proactive messages are saved to the existing Room message database and displayed as left-side AI messages.
- The Android UI shows a small syncing indicator with the text `正在同步服务端数据` while it is connected to the long-polling loop.
- The design keeps the proactive message generation layer separate from the delivery mechanism so future vivo Push integration can reuse it.

## Non-Goals

- No vivo Push integration in this version.
- No guarantee of delivery while the app is backgrounded, locked, or killed by the system.
- No Android foreground service or WorkManager background sync.
- No multi-user or multi-device routing.
- No authentication or authorization for proactive messages.
- No server-side database persistence for proactive messages.
- No JSON message envelope in this version.

## Runtime Architecture

```text
┌────────────────────────────────────┐
│ WatchingYou-server                  │
│                                    │
│  FastAPI lifespan startup           │
│        │                           │
│        ├─ starts auto publisher      │
│        │  every 5 minutes            │
│        │                             │
│        ▼                             │
│  in-memory proactive message broker  │
│        │                             │
│        ▼                             │
│  GET /poll                           │
│  - returns immediately when queued    │
│  - otherwise waits until message or   │
│    timeout                            │
└────────────────┬───────────────────┘
                 │ HTTP long polling
                 ▼
┌────────────────────────────────────┐
│ WatchingYou-Android-APP             │
│                                    │
│  MainActivity foreground lifecycle   │
│        │                             │
│        ├─ shows syncing indicator     │
│        │  正在同步服务端数据           │
│        │                             │
│        ├─ repeatedly calls GET /poll   │
│        │                             │
│        ├─ stores returned messages     │
│        │  as Sender.AI                 │
│        │                             │
│        └─ stops polling on background  │
└────────────────────────────────────┘
```

## Server Design

### Proactive Message Broker

Add `app/proactive_messages.py` with a small broker object responsible for proactive messages.

Responsibilities:

- Keep an in-memory queue of pending proactive messages.
- Provide `publish(content)` to enqueue a message and wake pending poll requests.
- Provide `poll(timeout_seconds)` to wait for and return the next message.
- Provide auto-publisher lifecycle helpers that publish the fixed message every 5 minutes.

The broker should be independent of FastAPI route handlers. `app/main.py` should only wire FastAPI startup/shutdown and expose the HTTP endpoint.

### Queue Policy

This version is single-user and global. A single in-memory queue is sufficient.

To avoid unbounded memory growth if the Android app is closed for a long time, keep at most 20 pending messages. If the queue is full, discard the oldest message before appending the new one.

```text
MAX_QUEUE_SIZE = 20
```

### Auto Publisher

The server starts an async background task during FastAPI lifespan startup.

Constants for the first version:

```text
AUTO_MESSAGE_INTERVAL_SECONDS = 300
AUTO_MESSAGE_CONTENT = "每隔5min自动发的消息"
POLL_DEFAULT_TIMEOUT_SECONDS = 30
POLL_MAX_TIMEOUT_SECONDS = 60
MAX_QUEUE_SIZE = 20
```

The first automatic message is published after the first 5-minute interval, not immediately on server startup. This matches the user-facing meaning of “every 5 minutes.” Tests can inject a short interval so they do not wait 5 real minutes.

On server shutdown, cancel the auto-publisher task cleanly.

### Long Poll Endpoint

Add:

```http
GET /poll?timeout_seconds=30
```

Keep the response format as `text/plain`, matching the existing `/health` and `/chat` endpoints.

When a message is available:

```http
200 OK
Content-Type: text/plain; charset=utf-8

每隔5min自动发的消息
```

When no message arrives before timeout:

```http
204 No Content
```

`timeout_seconds` handling:

- omitted: use 30 seconds
- less than 1 second: clamp to 1 second
- greater than 60 seconds: clamp to 60 seconds

Internal errors should return `500` and be logged by the server.

## Android Design

### API Client

Extend `WatchingYouApi` with a long-polling call, for example:

```kotlin
fun pollProactiveMessage(baseUrl: String, timeoutSeconds: Int = 30): String?
```

Behavior:

- `200`: return the response body as a non-null string.
- `204`: return `null`.
- non-2xx except `204`: throw an error.
- network failures and read timeouts: throw an error.

The HTTP read timeout must be longer than the server poll timeout, for example 35 seconds for a 30-second poll, otherwise the Android client may give up before the server intentionally returns `204`.

### Polling Coordinator

Add a focused Android component rather than growing `MainActivity` further. A suitable name is `ProactiveMessageSyncCoordinator`.

Responsibilities:

- Start polling when `MainActivity` is in the foreground and a server base URL is registered.
- Stop polling when `MainActivity` moves to the background.
- Call `WatchingYouApi.pollProactiveMessage()` in a loop.
- Insert each returned message into Room as `Sender.AI`.
- Notify the UI when sync state changes.
- Retry after failures with a short delay to avoid tight error loops.

The coordinator should depend on small injectable functions or interfaces for testability, similar to the existing `ChatSendCoordinator` style.

### Lifecycle

`MainActivity` should manage proactive sync through foreground lifecycle events:

- `onStart()`: start proactive sync if a server address exists.
- `onStop()`: stop proactive sync and cancel the current `/poll` request.
- `onDestroy()`: continue to clean up the Activity coroutine scope.

This ensures the basic version does not keep networking active when the app is backgrounded, reducing battery use and avoiding Android background execution restrictions.

If the user registers or changes the server address while the Activity is open, the app should restart the proactive sync loop with the new address.

### Sync Status UI

Add a lightweight status row below the top bar and above the message list.

Suggested layout:

```text
┌──────────────────────────────┐
│         WatchingYou    服务端 │
├──────────────────────────────┤
│  ◌ 正在同步服务端数据          │
├──────────────────────────────┤
│                              │
│        聊天消息列表           │
│                              │
├──────────────────────────────┤
│  输入消息...            发送  │
└──────────────────────────────┘
```

Implementation:

- A small indeterminate `ProgressBar`.
- A `TextView` for the status message.

Recommended states:

| Scenario | UI state |
| --- | --- |
| No registered server | Show `请先注册服务端`, no spinner |
| Polling or waiting for server | Show spinner and `正在同步服务端数据` |
| Received a proactive message | Keep syncing state and continue next poll |
| `204 No Content` | Keep syncing state and continue next poll |
| Network or server error | Show `服务端同步失败，稍后重试`, hide or stop spinner |
| Activity stopped | Stop polling; status row is no longer active |

Polling sync status must be independent from manual chat sending. A `/poll` failure should not disable the send button and should not create a red chat error bubble.

### Message Storage and Display

When `/poll` returns the fixed text, insert it into Room as:

```kotlin
Message(
    content = "每隔5min自动发的消息",
    sender = Sender.AI,
    timestamp = now()
)
```

The existing chat adapter will display it as a normal left-side AI message. After insertion, refresh the message list and scroll to the bottom.

## Error Handling

### Android

- Missing server registration: do not start polling; show `请先注册服务端`.
- `204 No Content`: do not insert a message; immediately start the next poll.
- Network failure or server failure: do not insert a chat message; update sync status to `服务端同步失败，稍后重试` and retry after a short delay.
- Activity backgrounded: cancel the active poll request.
- Server address changed: stop polling the old address and start polling the new address.

### Server

- Clamp `timeout_seconds` to `[1, 60]`.
- Return `204` for normal poll timeout without messages.
- Drop the oldest queued message when the queue is full.
- Cancel the auto-publisher on shutdown.

## Testing Plan

### Server Tests

Add tests for the proactive message broker and `/poll` endpoint:

1. Poll returns `200` and the message when a message is already queued.
2. Poll returns `204` when no message arrives before timeout.
3. `timeout_seconds` is clamped to the allowed range.
4. Publishing beyond `MAX_QUEUE_SIZE` drops the oldest messages.
5. The auto-publisher can publish using an injected short interval.
6. FastAPI lifespan starts and stops the auto-publisher cleanly.

### Android Tests and Manual Validation

Unit-testable areas:

1. `WatchingYouApi.pollProactiveMessage()` returns text on `200`.
2. `WatchingYouApi.pollProactiveMessage()` returns `null` on `204`.
3. `WatchingYouApi.pollProactiveMessage()` throws on non-2xx errors.
4. The polling coordinator does not start without a registered server.
5. The polling coordinator inserts `Sender.AI` messages on successful polls.
6. The polling coordinator does not insert `Sender.ERROR` messages on sync failures.

Manual validation:

1. Start `WatchingYou-server`.
2. Register the server in the Android app.
3. Confirm the chat screen shows `正在同步服务端数据` with a small spinner.
4. Wait about 5 minutes.
5. Confirm the chat list shows a left-side AI message: `每隔5min自动发的消息`.
6. Put the app in the background and confirm polling stops.
7. Bring the app to the foreground and confirm polling resumes.

## Future Extension: vivo Push

Future background or killed-app delivery should use vivo Push or another system-level push channel. This design keeps proactive message generation separate from long-poll delivery so the server can later route generated proactive messages to vivo Push instead of, or in addition to, `/poll`.

A future vivo Push version will need device registration, push credentials, token upload, and per-device routing. Those are intentionally out of scope for this foreground-only long-polling version.
