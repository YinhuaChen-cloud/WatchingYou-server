# =============================================================================
# WatchingYou-server 主应用入口
# 基于 FastAPI 框架，提供健康检查、聊天对话和主动消息轮询接口
# =============================================================================

from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import load_config
from app import deepseek
from app.proactive_messages import ProactiveMessageBroker
from app.reminders import ParsedReminder, ReminderScheduler, parse_remind_at

# 哪怕使用 uvicorn 启动，代码也会从这里往下一行一行执行

# 健康检查接口的问候语常量
GREETING = "Hello from WatchingYou-server"

# 加载应用配置（调用一次，缓存结果） 读项目根目录下的 config.yaml 文件，获取 DeepSeek API 密钥
_config = load_config()
# 从配置中提取 DeepSeek API 密钥，供后续 API 调用使用
_api_key = _config["deepseek_api_key"]

# 创建全局的主动消息代理器实例，用于管理主动推送消息的生产和消费
proactive_broker = ProactiveMessageBroker()

@asynccontextmanager
async def lifespan(app: FastAPI):
    reminder_scheduler = ReminderScheduler(
        broker=proactive_broker,
        api_key=_api_key,
        generate_message=deepseek.generate_reminder_message,
    )
    app.state.reminder_scheduler = reminder_scheduler
    yield
    await reminder_scheduler.shutdown()


# 创建 FastAPI 应用实例，绑定生命周期管理函数
app = FastAPI(title="WatchingYou Server", lifespan=lifespan)


# -----------------------------------------------------------------------
# GET /poll — 主动消息长轮询接口
# 客户端通过此接口等待服务器主动推送的消息
# timeout_seconds: 可选参数，指定最大等待时间（秒），无新消息时返回 204
# -----------------------------------------------------------------------
# server 收到 poll 请求时，自己向 proactive_broker 发送 poll 请求。若拿到消息返回给客户端，否则返回 204
@app.get("/poll", response_class=Response)
async def poll(timeout_seconds: Optional[float] = Query(default=None)) -> Response:
    # 调用消息代理器的 poll 方法，阻塞等待直到有新消息或超时
    message = await proactive_broker.poll(timeout_seconds=timeout_seconds)
    # 如果超时仍未收到消息，返回 HTTP 204 No Content（表示没有新消息）
    if message is None:
        return Response(status_code=204)
    # 有新消息：将消息对象序列化为 JSON 格式返回给客户端
    return JSONResponse(content=message.to_dict())


# -----------------------------------------------------------------------
# GET /health — 健康检查接口
# 可用于负载均衡器或监控系统检测服务是否正常运行
# -----------------------------------------------------------------------
@app.get("/health", response_class=Response)
def health() -> Response:
    # 返回纯文本问候语，表示服务健康存活
    return Response(content=GREETING, media_type="text/plain")


# -----------------------------------------------------------------------
# POST /chat — 对话接口
# 接收用户文本消息，转发给 DeepSeek AI 处理，返回 AI 回复
# 特殊命令：发送 "/restart" 可重置对话历史
# -----------------------------------------------------------------------
@app.post("/chat", response_class=Response)
async def chat(request: Request) -> Response:
    # 读取请求体原始字节，解码为 UTF-8 字符串，去除首尾空白
    body = (await request.body()).decode("utf-8").strip()
    # 如果请求体为空，返回 400 Bad Request 错误提示
    if not body:
        return Response(content="message body is required", status_code=400, media_type="text/plain")

    # 特殊命令处理：如果用户发送 "/restart"，重置 DeepSeek 对话历史
    if body == "/restart":
        deepseek.reset_history()
        return Response(content="对话已重置。", media_type="text/plain")

    try:
        parse_result = await run_in_threadpool(deepseek.parse_reminder_request, body, api_key=_api_key)
        if parse_result.data is None:
            return Response(content=parse_result.raw_reply, media_type="text/plain")

        if parse_result.data.get("is_reminder"):
            remind_at = parse_remind_at(str(parse_result.data.get("remind_at", "")))
            task = parse_result.data.get("task")
            confirmation = parse_result.data.get("confirmation")
            if remind_at is None or not isinstance(task, str) or not isinstance(confirmation, str):
                return Response(content=parse_result.raw_reply, media_type="text/plain")

            reminder = ParsedReminder(
                remind_at=remind_at,
                task=task,
                confirmation=confirmation,
            )
            request.app.state.reminder_scheduler.schedule(reminder)
            return Response(content=confirmation, media_type="text/plain")

        reply = await run_in_threadpool(deepseek.chat, body, api_key=_api_key)
        return Response(content=reply, media_type="text/plain")
    except httpx.HTTPStatusError as e:
        # 捕获 HTTP 状态错误（如 DeepSeek API 返回 4xx/5xx）
        # 构造包含状态码和响应体的错误信息
        error_text = f"DeepSeek API error {e.response.status_code}: {e.response.text}"
        # 返回 502 Bad Gateway，表示上游服务出错
        return Response(content=error_text, status_code=502, media_type="text/plain")
    except Exception as e:
        # 捕获所有其他未预期的异常（网络错误、超时等）
        # 返回 502 状态码和错误描述，避免服务崩溃
        return Response(content=f"upstream error: {e}", status_code=502, media_type="text/plain")