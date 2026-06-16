# WatchingYou Server — DeepSeek Proxy Design

## Overview

Transform the WatchingYou server from a static greeting responder into a proxy between the Android client and the DeepSeek API. The server maintains a single global in-memory conversation history, forwarding user messages to DeepSeek and returning AI replies as plain text.

## Configuration

A `config.yaml` file in the project root holds the DeepSeek API key:

```yaml
deepseek_api_key: "your_api_key_here"
```

- `config.yaml` is not committed to git (added to `.gitignore`)
- `config.yaml.example` is committed as a template for deployers
- `app/config.py` reads and validates the config at startup; if the file is missing or the key is empty/placeholder, the process exits with a clear error message before accepting any requests
- New dependency: `pyyaml` added to `requirements.txt`

## Architecture

### File Structure

```
WatchingYou-server/
├── config.yaml.example       # committed template
├── config.yaml               # deployer-filled, gitignored
├── requirements.txt          # add pyyaml
├── app/
│   ├── config.py             # reads and validates config.yaml
│   ├── deepseek.py           # DeepSeek API client + in-memory history
│   └── main.py               # FastAPI endpoints (modify /chat)
└── tests/
    ├── test_main.py          # update /chat tests
    └── test_deepseek.py      # new: DeepSeek client unit tests
```

### Data Flow

```
Client POST /chat (text/plain: user message)
  → main.py extracts message text
  → deepseek.py appends to history, calls DeepSeek API
  → DeepSeek returns AI reply
  → deepseek.py appends AI reply to history
  → main.py returns AI reply (text/plain)
```

### Conversation History

Stored as a module-level list in `deepseek.py`:

```python
history: list[dict] = []
# Each entry: {"role": "user"|"assistant", "content": "..."}
```

The `chat(message: str) -> str` function appends the user message, POSTs the full history to DeepSeek, appends the AI reply, and returns the reply text. History lives only in memory — cleared on server restart.

## Endpoints

### `GET /health`

Unchanged. Returns `"Hello from WatchingYou-server"` as `text/plain`. Used by the Android client to test connectivity and register the server.

### `POST /chat`

- Request body: plain text (`text/plain`), the user's message
- Empty body → HTTP 400
- On success → HTTP 200, plain text AI reply
- On DeepSeek API error (non-2xx or network failure) → HTTP 502, plain text error description

## DeepSeek API Call

- Endpoint: `https://api.deepseek.com/chat/completions`
- Model: `deepseek-chat`
- HTTP client: `httpx` (already in `requirements.txt`)
- Timeout: 30 seconds
- No system prompt
- Request format follows OpenAI-compatible chat completions schema

## Error Handling

| Scenario | Server response |
|---|---|
| Empty request body | HTTP 400, plain text description |
| DeepSeek API non-2xx | HTTP 502, plain text with status code and message |
| Network timeout / connection error | HTTP 502, plain text with error description |
| Missing or invalid `config.yaml` | Process exits at startup with clear error message |

The Android client (`WatchingYouApi.kt`) already handles non-2xx responses by throwing `IllegalStateException("HTTP $responseCode: $responseBody")`, which the UI displays in the chat as an error message.
