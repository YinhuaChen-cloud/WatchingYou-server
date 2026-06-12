# WatchingYou-server

Minimal FastAPI server for WatchingYou-Android-APP.

## Behavior

Both endpoints return the exact plain-text string:

```text
Hello from WatchingYou-server
```

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
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Verify

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat
```

Both commands should print:

```text
Hello from WatchingYou-server
```

## Install as a systemd service

This example deploys the repository to `/opt/WatchingYou-server`. Keep the deployed app and virtualenv owned by `root`; the systemd unit runs as `www-data`, so the files only need to be readable and executable by `www-data`. This first server does not require a writable data directory.

```bash
sudo mkdir -p /opt/WatchingYou-server
sudo rsync -a --delete ./ /opt/WatchingYou-server/
cd /opt/WatchingYou-server
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
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
