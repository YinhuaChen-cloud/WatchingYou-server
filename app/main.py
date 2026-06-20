import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import load_config
from app import deepseek
from app.proactive_messages import ProactiveMessageBroker, run_auto_publisher

GREETING = "Hello from WatchingYou-server"

_config = load_config()
_api_key = _config["deepseek_api_key"]

proactive_broker = ProactiveMessageBroker()
_auto_publisher_stop: asyncio.Event | None = None
_auto_publisher_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _auto_publisher_stop, _auto_publisher_task
    _auto_publisher_stop = asyncio.Event()
    _auto_publisher_task = asyncio.create_task(
        run_auto_publisher(proactive_broker, stop_event=_auto_publisher_stop)
    )
    yield
    _auto_publisher_stop.set()
    await _auto_publisher_task
    _auto_publisher_task = None
    _auto_publisher_stop = None


app = FastAPI(title="WatchingYou Server", lifespan=lifespan)


@app.get("/poll", response_class=Response)
async def poll(timeout_seconds: Optional[float] = Query(default=None)) -> Response:
    message = await proactive_broker.poll(timeout_seconds=timeout_seconds)
    if message is None:
        return Response(status_code=204)
    return JSONResponse(content=message.to_dict())


@app.get("/health", response_class=Response)
def health() -> Response:
    return Response(content=GREETING, media_type="text/plain")


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