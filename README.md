# WatchingYou-server

FastAPI server that proxies chat messages from WatchingYou-Android-APP to the DeepSeek API.

## Behavior

- `GET /health` — returns `Hello from WatchingYou-server` (used by the Android client to verify connectivity)
- `POST /chat` — forwards the plain-text message body to DeepSeek and returns the AI reply as plain text; maintains a single global in-memory conversation history (cleared on restart). The server is configured with a "学习工作监督员" (study/work supervisor) persona that uses a snarky tone to keep users focused on productive tasks.
- `POST /chat` with body `/restart` — resets the conversation history to its initial state (keeps only the supervisor persona), returning "对话已重置。" without calling the DeepSeek API
- `POST /chat` with a natural-language reminder request such as `哟，2:30 提醒我开会` — asks DeepSeek to parse the reminder, schedules it in memory, and immediately returns a confirmation reply. When the reminder fires, the server asks DeepSeek to generate a reminder message and queues it for `/poll`. Scheduled reminders are lost if the server restarts.
- `GET /poll?timeout_seconds=30` — long-polling endpoint for proactive messages. Returns `200 application/json` with `{"content": "...", "timestamp": <unix-epoch-ms>, "type": "ai"}` for normal proactive messages, `type: "error"` for red error proactive messages, or `204 No Content` when the poll times out without a message. `timeout_seconds` is optional (default 30, clamped to 1–60). Proactive delivery is foreground-only; no vivo Push, FCM, or background service is involved in this version.

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
# 创建 Python 虚拟环境，隔离项目依赖，避免污染系统 Python 环境
python3 -m venv .venv
# 激活虚拟环境，之后 pip 安装的包都会隔离在 .venv 内
. .venv/bin/activate
# 安装项目所需的 Python 依赖包
pip install -r requirements.txt
```

## Run locally

```bash
# see Configuration section above to set up config.yaml
. .venv/bin/activate
# uvicorn 是 ASGI 服务器，用来运行 FastAPI 应用
# app.main:app 表示从 app/main.py 中导入名为 app 的 FastAPI 实例并启动
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Verify

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "你好"
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "/restart"
```

`/health` prints `Hello from WatchingYou-server`. `/chat` prints the DeepSeek reply (with supervisor persona). `/restart` resets the conversation history. `/poll` returns `200` with a proactive message JSON object `{"content": "...", "timestamp": <unix-epoch-ms>}` when available, or `204` on timeout.

```bash
# Queue behavior is now reminder-driven. Start the server, send a near-future reminder,
# then poll until the reminder message is returned.
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "1 分钟后提醒我开会"
curl http://127.0.0.1:8000/poll
```

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
