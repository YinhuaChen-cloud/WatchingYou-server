import httpx
from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool

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