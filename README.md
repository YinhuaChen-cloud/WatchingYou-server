# WatchingYou-server

FastAPI server that proxies chat messages from WatchingYou-Android-APP to the DeepSeek API.

## Behavior

- `GET /health` — returns `Hello from WatchingYou-server` (used by the Android client to verify connectivity)
- `POST /chat` — forwards the plain-text message body to DeepSeek and returns the AI reply as plain text; maintains a single global in-memory conversation history (cleared on restart). The server is configured with a "学习工作监督员" (study/work supervisor) persona that uses a snarky tone to keep users focused on productive tasks.
- `POST /chat` with body `/restart` — resets the conversation history to its initial state (keeps only the supervisor persona), returning "对话已重置。" without calling the DeepSeek API

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
# see Configuration section above to set up config.yaml
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Verify

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "你好"
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: text/plain" -d "/restart"
```

`/health` prints `Hello from WatchingYou-server`. `/chat` prints the DeepSeek reply (with supervisor persona). `/restart` resets the conversation history.

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
