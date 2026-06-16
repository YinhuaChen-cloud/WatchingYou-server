# DeepSeek Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the `/chat` endpoint from returning a static greeting into a proxy that forwards user messages to DeepSeek and returns AI replies, with a single global in-memory conversation history.

**Architecture:** A new `app/config.py` reads `config.yaml` at startup and fails fast if the API key is missing. A new `app/deepseek.py` owns the conversation history list and the `httpx` call to DeepSeek. `app/main.py`'s `/chat` endpoint is updated to delegate to `deepseek.chat()`.

**Tech Stack:** Python 3, FastAPI, httpx (existing), pyyaml (new), pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.yaml.example` | Create | Deployer template, committed to git |
| `config.yaml` | Create (deployer fills) | Actual API key, gitignored |
| `.gitignore` | Modify | Add `config.yaml` |
| `requirements.txt` | Modify | Add `pyyaml` |
| `app/config.py` | Create | Load and validate `config.yaml`, exit on bad config |
| `app/deepseek.py` | Create | In-memory history, `chat(message) -> str`, calls DeepSeek API |
| `app/main.py` | Modify | `/chat` delegates to `deepseek.chat()`, handles empty body (400) and errors (502) |
| `tests/test_deepseek.py` | Create | Unit tests for `deepseek.py` with mocked `httpx` |
| `tests/test_main.py` | Modify | Update `/chat` tests to mock `deepseek.chat` |

---

### Task 1: Add pyyaml dependency and config template

**Files:**
- Modify: `requirements.txt`
- Create: `config.yaml.example`
- Modify: `.gitignore`

- [ ] **Step 1: Add pyyaml to requirements.txt**

Replace the contents of `requirements.txt` with:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pytest==8.3.4
httpx==0.28.1
pyyaml==6.0.2
```

- [ ] **Step 2: Create config.yaml.example**

Create `config.yaml.example` at the project root:

```yaml
deepseek_api_key: "your_api_key_here"
```

- [ ] **Step 3: Add config.yaml to .gitignore**

Append `config.yaml` to `.gitignore` so the file with the real API key is never committed:

```
.venv/
__pycache__/
.pytest_cache/
*.pyc
config.yaml
```

- [ ] **Step 4: Install updated dependencies**

```bash
. .venv/bin/activate
pip install -r requirements.txt
```

Expected: pyyaml installs without errors.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config.yaml.example .gitignore
git commit -m "chore: add pyyaml dep, config template, gitignore config.yaml"
```

---

### Task 2: Implement app/config.py with fail-fast validation

**Files:**
- Create: `app/config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import sys
import pytest
import yaml


def write_config(tmp_path, content: str):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(content)
    return str(config_file)


def test_load_config_returns_api_key(tmp_path):
    path = write_config(tmp_path, 'deepseek_api_key: "sk-test-key"')
    from app.config import load_config
    result = load_config(path)
    assert result["deepseek_api_key"] == "sk-test-key"


def test_load_config_exits_when_file_missing(tmp_path, capsys):
    from app.config import load_config
    missing = str(tmp_path / "nonexistent.yaml")
    with pytest.raises(SystemExit):
        load_config(missing)
    captured = capsys.readouterr()
    assert "config.yaml" in captured.out or "config.yaml" in captured.err


def test_load_config_exits_when_key_is_placeholder(tmp_path, capsys):
    path = write_config(tmp_path, 'deepseek_api_key: "your_api_key_here"')
    from app.config import load_config
    with pytest.raises(SystemExit):
        load_config(path)


def test_load_config_exits_when_key_is_empty(tmp_path, capsys):
    path = write_config(tmp_path, 'deepseek_api_key: ""')
    from app.config import load_config
    with pytest.raises(SystemExit):
        load_config(path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: ImportError or AttributeError — `app.config` does not exist yet.

- [ ] **Step 3: Implement app/config.py**

Create `app/config.py`:

```python
import sys
import yaml

_PLACEHOLDER = "your_api_key_here"


def load_config(path: str = "config.yaml") -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: config.yaml not found at '{path}'.", file=sys.stderr)
        print("Copy config.yaml.example to config.yaml and fill in your DeepSeek API key.", file=sys.stderr)
        sys.exit(1)

    key = (data or {}).get("deepseek_api_key", "")
    if not key or key == _PLACEHOLDER:
        print("ERROR: deepseek_api_key is missing or still set to the placeholder value.", file=sys.stderr)
        print("Edit config.yaml and set a real DeepSeek API key.", file=sys.stderr)
        sys.exit(1)

    return data
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add config loader with fail-fast validation"
```

---

### Task 3: Implement app/deepseek.py

**Files:**
- Create: `app/deepseek.py`
- Create: `tests/test_deepseek.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deepseek.py`:

```python
import pytest
import httpx
from unittest.mock import patch, MagicMock


def make_deepseek_response(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return mock_resp


def test_chat_returns_ai_reply():
    import app.deepseek as ds
    ds._history.clear()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Hello!")) as mock_post:
        reply = ds.chat("Hi")

    assert reply == "Hello!"


def test_chat_appends_to_history():
    import app.deepseek as ds
    ds._history.clear()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("I'm fine")):
        ds.chat("How are you?")

    assert len(ds._history) == 2
    assert ds._history[0] == {"role": "user", "content": "How are you?"}
    assert ds._history[1] == {"role": "assistant", "content": "I'm fine"}


def test_chat_sends_full_history_on_second_message():
    import app.deepseek as ds
    ds._history.clear()

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Hi there")) as mock_post:
        ds.chat("Hello")

    with patch.object(ds._client, "post", return_value=make_deepseek_response("Sure!")) as mock_post:
        ds.chat("Can you help?")

    called_messages = mock_post.call_args[1]["json"]["messages"]
    assert len(called_messages) == 3
    assert called_messages[0]["role"] == "user"
    assert called_messages[1]["role"] == "assistant"
    assert called_messages[2]["role"] == "user"


def test_chat_raises_on_api_error():
    import app.deepseek as ds
    ds._history.clear()

    error_resp = MagicMock()
    error_resp.status_code = 401
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized", request=MagicMock(), response=error_resp
    )

    with patch.object(ds._client, "post", return_value=error_resp):
        with pytest.raises(httpx.HTTPStatusError):
            ds.chat("Hello")


def test_chat_does_not_append_to_history_on_api_error():
    import app.deepseek as ds
    ds._history.clear()

    error_resp = MagicMock()
    error_resp.status_code = 500
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=error_resp
    )

    with patch.object(ds._client, "post", return_value=error_resp):
        with pytest.raises(httpx.HTTPStatusError):
            ds.chat("Hello")

    assert len(ds._history) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_deepseek.py -v
```

Expected: ImportError — `app.deepseek` does not exist yet.

- [ ] **Step 3: Implement app/deepseek.py**

Create `app/deepseek.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_deepseek.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/deepseek.py tests/test_deepseek.py
git commit -m "feat: add DeepSeek client with in-memory conversation history"
```

---

### Task 4: Update app/main.py to wire up config and deepseek

**Files:**
- Modify: `app/main.py`
- Create: `config.yaml` (local only, not committed)

- [ ] **Step 1: Create a local config.yaml for development**

```bash
cp config.yaml.example config.yaml
```

Then edit `config.yaml` and replace `"your_api_key_here"` with your actual DeepSeek API key.

- [ ] **Step 2: Update app/main.py**

Replace the full contents of `app/main.py`:

```python
import httpx
from fastapi import FastAPI, Request, Response

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

    try:
        reply = deepseek.chat(body, api_key=_api_key)
        return Response(content=reply, media_type="text/plain")
    except httpx.HTTPStatusError as e:
        error_text = f"DeepSeek API error {e.response.status_code}: {e.response.text}"
        return Response(content=error_text, status_code=502, media_type="text/plain")
    except Exception as e:
        return Response(content=f"upstream error: {e}", status_code=502, media_type="text/plain")
```

- [ ] **Step 3: Verify the server starts**

```bash
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Expected: server starts without error. If you see `ERROR: deepseek_api_key is missing`, your `config.yaml` has not been filled in.

Stop the server with Ctrl+C.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: wire config and DeepSeek client into /chat endpoint"
```

---

### Task 5: Update tests/test_main.py for the new /chat behavior

**Files:**
- Modify: `tests/test_main.py`

- [ ] **Step 1: Replace tests/test_main.py**

```python
from unittest.mock import patch
import httpx
import pytest
from fastapi.testclient import TestClient


def make_app():
    with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
        import importlib
        import app.main as main_module
        importlib.reload(main_module)
        return main_module.app


@pytest.fixture
def client():
    with patch("app.config.load_config", return_value={"deepseek_api_key": "sk-test"}):
        from app.main import app
        return TestClient(app)


def test_health_returns_plain_text_greeting(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello from WatchingYou-server"


def test_chat_returns_ai_reply(client):
    with patch("app.main.deepseek.chat", return_value="Hello from DeepSeek"):
        response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello from DeepSeek"


def test_chat_empty_body_returns_400(client):
    response = client.post("/chat", content="", headers={"Content-Type": "text/plain"})

    assert response.status_code == 400


def test_chat_deepseek_http_error_returns_502(client):
    mock_response = httpx.Response(500, text="Internal Server Error")
    error = httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://x"), response=mock_response)

    with patch("app.main.deepseek.chat", side_effect=error):
        response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 502
    assert "500" in response.text


def test_chat_network_error_returns_502(client):
    with patch("app.main.deepseek.chat", side_effect=Exception("connection refused")):
        response = client.post("/chat", content="Hi", headers={"Content-Type": "text/plain"})

    assert response.status_code == 502
```

- [ ] **Step 2: Run all tests**

```bash
pytest -v
```

Expected: all tests pass. Note: `test_main.py` patches `load_config` so no real `config.yaml` is needed at test time.

- [ ] **Step 3: Commit**

```bash
git add tests/test_main.py
git commit -m "test: update /chat endpoint tests for DeepSeek proxy behavior"
```

---

### Task 6: Update README.md for deployers

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README.md**

Replace the **Behavior** section and add a **Configuration** section. The full updated README:

````markdown
# WatchingYou-server

FastAPI server that proxies chat messages from WatchingYou-Android-APP to the DeepSeek API.

## Behavior

- `GET /health` — returns `Hello from WatchingYou-server` (used by the Android client to verify connectivity)
- `POST /chat` — forwards the plain-text message body to DeepSeek and returns the AI reply as plain text; maintains a single global in-memory conversation history (cleared on restart)

## Configuration

Before running the server, create `config.yaml` from the template and fill in your DeepSeek API key:

```bash
cp config.yaml.example config.yaml
# Edit config.yaml and replace "your_api_key_here" with your actual key
```

The server will refuse to start if `config.yaml` is missing or the key has not been set.

## Local setup on Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl rsync
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run locally

```bash
cp config.yaml.example config.yaml
# edit config.yaml: set deepseek_api_key
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Verify

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "你好"
```

`/health` prints `Hello from WatchingYou-server`. `/chat` prints the DeepSeek reply.

## Install as a systemd service

This example deploys the repository to `/opt/WatchingYou-server`.

```bash
sudo mkdir -p /opt/WatchingYou-server
sudo rsync -a --delete ./ /opt/WatchingYou-server/
cd /opt/WatchingYou-server
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo cp config.yaml.example config.yaml
# Edit /opt/WatchingYou-server/config.yaml: set deepseek_api_key
sudo chown -R root:root /opt/WatchingYou-server
sudo find /opt/WatchingYou-server -type d -exec chmod 755 {} +
sudo find /opt/WatchingYou-server -type f -exec chmod 644 {} +
sudo find /opt/WatchingYou-server/.venv/bin -type f -exec chmod 755 {} +
sudo cp deploy/watchingyou-server.service /etc/systemd/system/watchingyou-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now watchingyou-server
systemctl status watchingyou-server
curl http://127.0.0.1:8000/health
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README for DeepSeek proxy configuration and usage"
```
