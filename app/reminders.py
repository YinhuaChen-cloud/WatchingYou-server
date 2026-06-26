import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from app.proactive_messages import ProactiveMessageBroker


@dataclass(frozen=True)
class ParsedReminder:
    remind_at: datetime
    task: str
    confirmation: str


def parse_remind_at(value: str) -> Optional[datetime]:
    try:
        remind_at = datetime.fromisoformat(value)
    except ValueError:
        return None
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)
    if remind_at <= datetime.now(timezone.utc):
        return None
    return remind_at


class ReminderScheduler:
    def __init__(
        self,
        broker: ProactiveMessageBroker,
        api_key: str,
        generate_message: Callable[[str, str], str],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._broker = broker
        self._api_key = api_key
        self._generate_message = generate_message
        self._now = now
        self._tasks: set[asyncio.Task] = set()

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def schedule(self, reminder: ParsedReminder) -> bool:
        if reminder.remind_at <= self._now():
            delay_seconds = 0
        else:
            delay_seconds = (reminder.remind_at - self._now()).total_seconds()
        task = asyncio.create_task(self._run_reminder(reminder, delay_seconds))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run_reminder(self, reminder: ParsedReminder, delay_seconds: float) -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        try:
            content = self._generate_message(reminder.task, self._api_key)
            await self._broker.publish(content, message_type="ai")
        except Exception:
            await self._broker.publish("主动消息生成失败", message_type="error")
