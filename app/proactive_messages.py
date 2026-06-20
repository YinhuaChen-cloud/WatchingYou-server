import asyncio
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Callable, Optional

# --- Constants ---

AUTO_MESSAGE_INTERVAL_SECONDS = 360
AUTO_MESSAGE_CONTENT = "每隔6min自动发送消息"
POLL_DEFAULT_TIMEOUT_SECONDS = 30
POLL_MIN_TIMEOUT_SECONDS = 1
POLL_MAX_TIMEOUT_SECONDS = 60
MAX_QUEUE_SIZE = 20


# --- Helpers ---

def current_time_millis() -> int:
    return int(time.time() * 1000)


def clamp_poll_timeout(timeout_seconds: Optional[float]) -> float:
    if timeout_seconds is None:
        return POLL_DEFAULT_TIMEOUT_SECONDS
    if timeout_seconds < POLL_MIN_TIMEOUT_SECONDS:
        return POLL_MIN_TIMEOUT_SECONDS
    if timeout_seconds > POLL_MAX_TIMEOUT_SECONDS:
        return POLL_MAX_TIMEOUT_SECONDS
    return timeout_seconds


# --- Structured message ---

@dataclass(frozen=True)
class ProactiveMessage:
    content: str
    timestamp: int

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


# --- Broker ---

class ProactiveMessageBroker:
    def __init__(
        self,
        max_queue_size: int = MAX_QUEUE_SIZE,
        now_ms: Callable[[], int] = current_time_millis,
    ) -> None:
        self.max_queue_size = max_queue_size
        self._now_ms = now_ms
        self._queue: deque[ProactiveMessage] = deque()
        self._condition = asyncio.Condition()

    async def publish(
        self, content: str, timestamp_ms: Optional[int] = None
    ) -> None:
        timestamp = timestamp_ms if timestamp_ms is not None else self._now_ms()
        msg = ProactiveMessage(content=content, timestamp=timestamp)
        async with self._condition:
            if len(self._queue) >= self.max_queue_size:
                self._queue.popleft()  # drop oldest
            self._queue.append(msg)
            self._condition.notify_all()

    async def poll(
        self, timeout_seconds: Optional[float] = None
    ) -> Optional[ProactiveMessage]:
        timeout = clamp_poll_timeout(timeout_seconds)
        async with self._condition:
            if self._queue:
                return self._queue.popleft()

            try:
                await asyncio.wait_for(
                    self._condition.wait(), timeout=timeout
                )
            except asyncio.TimeoutError:
                return None

            # After being notified, check again
            if self._queue:
                return self._queue.popleft()
            return None


# --- Auto publisher ---

async def run_auto_publisher(
    broker: ProactiveMessageBroker,
    interval_seconds: float = AUTO_MESSAGE_INTERVAL_SECONDS,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    while True:
        # Wait for the interval, checking stop_event periodically
        if stop_event is not None:
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=interval_seconds
                )
                # stop_event was set
                return
            except asyncio.TimeoutError:
                pass  # interval elapsed, proceed to publish
        else:
            await asyncio.sleep(interval_seconds)

        await broker.publish(AUTO_MESSAGE_CONTENT)