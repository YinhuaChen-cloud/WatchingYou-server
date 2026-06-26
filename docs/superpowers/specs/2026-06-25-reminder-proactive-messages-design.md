# Reminder-driven proactive messages design

## Goal

Add reminder support to WatchingYou so the Android app can send a natural-language request such as “哟，2:30 提醒我开会”, the server schedules an in-memory reminder, DeepSeek generates a reminder message at the target time, and the Android app receives it through the existing `/poll` long-polling flow.

This feature replaces the current fixed six-minute test proactive message. The proactive queue and `/poll` endpoint remain, but the fixed auto publisher should no longer run.

## Current context

WatchingYou-server is a FastAPI app with:

- `POST /chat` for forwarding user text to DeepSeek and returning the assistant reply.
- A single global in-memory DeepSeek conversation history.
- `ProactiveMessageBroker` for queueing proactive messages.
- `GET /poll` for Android foreground long polling.
- A fixed `run_auto_publisher()` task that currently publishes a test message every six minutes.

WatchingYou-Android-APP already stores polled proactive messages in Room and displays them in the chat UI. It should continue polling `/poll`; only the proactive message schema needs a small extension for error messages.

## Recommended approach

Use a server-side in-memory reminder scheduler:

1. `/chat` receives the user's message.
2. The server asks DeepSeek to determine whether the message is a reminder request and, if so, extract structured reminder data.
3. If the message is not a reminder, the server keeps the existing normal chat behavior.
4. If it is a reminder, the server creates an in-memory asyncio reminder task and immediately returns DeepSeek's confirmation text to Android.
5. When the reminder time arrives, the server calls DeepSeek again to generate a reminder message using the existing conversation context.
6. The generated message is published to `ProactiveMessageBroker`.
7. Android receives the message through the existing foreground `/poll` loop and displays it.

This keeps the first version small, avoids adding persistence, and reuses the current proactive delivery path.

## Server architecture

### `deepseek.py`

Keep the existing shared conversation history. Add two capabilities:

- Reminder parsing: ask DeepSeek to classify the user message and extract a structured result containing:
  - `is_reminder`: boolean
  - `remind_at`: absolute timestamp in an ISO-like format when `is_reminder` is true
  - `task`: reminder subject
  - `confirmation`: user-facing confirmation text
- Reminder generation: when a reminder fires, ask DeepSeek to generate a short Chinese reminder message that follows the existing “学习工作监督员” persona.

Reminder-related calls should affect the same conversation history because reminders are part of the user's ongoing conversation.

### `reminders.py`

Add a focused reminder scheduler module that:

- Accepts a parsed reminder with target time, task text, and confirmation.
- Creates an `asyncio.Task` that sleeps until the target time.
- Calls the DeepSeek reminder generation function when the reminder fires.
- Publishes the resulting proactive message into `ProactiveMessageBroker`.
- Tracks active tasks so application shutdown can cancel them.

Reminders are in memory only. They are lost when the server restarts.

### `main.py`

Update FastAPI wiring:

- Stop starting `run_auto_publisher()` in `lifespan`; the six-minute fixed proactive message is no longer needed.
- Initialize the reminder scheduler with `proactive_broker` and the DeepSeek API key.
- Shut down the reminder scheduler during application shutdown.
- In `/chat`, attempt reminder parsing before falling back to normal chat behavior.

## `/chat` behavior

For each non-empty user message:

1. Ask DeepSeek to parse it as a possible reminder.
2. If parsing returns a valid reminder:
   - Schedule the reminder.
   - Return the `confirmation` text as plain text.
3. If parsing returns a valid non-reminder result:
   - Use the existing `deepseek.chat()` flow.
4. If the DeepSeek parsing response cannot be parsed as the expected structured format:
   - Return DeepSeek's raw reply directly to the user as plain text.
   - Do not create a reminder.

The `/restart` command should keep resetting the shared DeepSeek history. It should not be expanded to clear scheduled reminders unless explicitly added later.

## Time handling

DeepSeek should return an absolute reminder time. The server validates it before scheduling.

Rules:

- If the user gives a time without a date and that time has already passed today, interpret it as tomorrow.
- Explicit past dates should fail validation and should not create a reminder.
- This version supports one reminder per `/chat` message. If the user asks for multiple reminders in one sentence, DeepSeek should extract only the clearest one.

## Proactive message schema

Extend proactive messages with a type field:

```json
{
  "content": "别发呆了，该开会了。",
  "timestamp": 1782369000000,
  "type": "ai"
}
```

Error proactive message:

```json
{
  "content": "主动消息生成失败",
  "timestamp": 1782369000000,
  "type": "error"
}
```

Rules:

- `type="ai"` means a normal AI proactive message.
- `type="error"` means Android should render the message with the existing red error style.
- Missing `type` remains backward-compatible and should be treated as `ai` by Android.

## Reminder trigger behavior

When a reminder fires:

- On successful DeepSeek generation, publish a proactive message with `type="ai"`.
- If DeepSeek generation fails, publish `content="主动消息生成失败"` with `type="error"`.
- Messages are queued even when Android is offline or not in the foreground. Android receives them later through `/poll`.
- If the proactive queue is full, keep the existing broker behavior of dropping the oldest message.

## Android changes

Android should keep the existing long-polling flow. Required changes are limited to proactive message parsing and storage/display:

- Add a `type` field to the proactive message model, defaulting missing values to `ai`.
- Treat `type="ai"` as the current AI sender behavior.
- Treat `type="error"` as the existing red error message style.
- Keep `/chat` responses unchanged; parsing failures returned from `/chat` are plain AI text, not red errors.

## Error handling

- Empty `/chat` body remains a 400 error.
- Reminder parse structured output invalid: return DeepSeek's raw reply, do not schedule.
- Reminder time invalid or explicitly in the past: return DeepSeek's raw reply as plain text, do not schedule.
- Reminder generation failure at trigger time: publish red proactive error message `主动消息生成失败`.
- Server restart: lose scheduled reminders.
- Android offline: queue reminder messages until Android polls.

## Tests

Server tests should cover:

- Successful reminder parse schedules a reminder and returns confirmation.
- Reminder parse failure returns raw DeepSeek output and does not schedule.
- Non-reminder messages keep existing normal chat behavior.
- Reminder trigger success publishes a `type="ai"` proactive message.
- Reminder trigger generation failure publishes `content="主动消息生成失败"` and `type="error"`.
- `/poll` returns `content`, `timestamp`, and `type`.
- Lifespan shutdown cancels active reminder tasks.
- The fixed six-minute auto publisher no longer starts.

Android tests should cover:

- `WatchingYouApi.pollProactiveMessage()` parses `type="ai"`.
- Missing `type` is treated as `ai`.
- `type="error"` is stored and displayed with the existing error style.
- Existing server registration, normal chat, and long-polling behavior continue to work.

## Out of scope

- Persisting reminders across server restarts.
- Background Android push notifications.
- Multiple reminders from one user message.
- Multi-user or per-device reminder isolation.
- Deleting, editing, listing, or snoozing reminders.
