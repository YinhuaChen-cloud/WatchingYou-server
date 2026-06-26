from datetime import datetime, timedelta, timezone

import asyncio

from app.proactive_messages import ProactiveMessageBroker
from app.reminders import ParsedReminder, ReminderScheduler, parse_remind_at


def test_parse_remind_at_accepts_future_iso_timestamp():
    value = "2999-01-02T03:04:05+00:00"

    result = parse_remind_at(value)

    assert result == datetime(2999, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_parse_remind_at_rejects_invalid_timestamp():
    assert parse_remind_at("not-a-timestamp") is None


def test_parse_remind_at_rejects_past_time():
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    assert parse_remind_at(past) is None


def test_scheduler_publishes_generated_message_when_due():
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 123)
        scheduler = ReminderScheduler(
            broker=broker,
            api_key="secret",
            generate_message=lambda task, api_key: f"提醒：{task}",
            now=lambda: datetime.now(timezone.utc),
        )
        reminder = ParsedReminder(
            remind_at=datetime.now(timezone.utc),
            task="开会",
            confirmation="好",
        )

        assert scheduler.schedule(reminder) is True
        await asyncio.sleep(0.05)

        result = await broker.poll(timeout_seconds=1)
        assert result is not None
        assert result.content == "提醒：开会"
        assert result.timestamp == 123
        assert result.type == "ai"

        await scheduler.shutdown()

    asyncio.run(_test())


def test_scheduler_publishes_error_message_when_generation_fails():
    async def _test():
        broker = ProactiveMessageBroker(now_ms=lambda: 456)

        def fail(task: str, api_key: str) -> str:
            raise RuntimeError("boom")

        scheduler = ReminderScheduler(
            broker=broker,
            api_key="secret",
            generate_message=fail,
            now=lambda: datetime.now(timezone.utc),
        )
        reminder = ParsedReminder(
            remind_at=datetime.now(timezone.utc),
            task="开会",
            confirmation="好",
        )

        assert scheduler.schedule(reminder) is True
        await asyncio.sleep(0.05)

        result = await broker.poll(timeout_seconds=1)
        assert result is not None
        assert result.content == "主动消息生成失败"
        assert result.timestamp == 456
        assert result.type == "error"

        await scheduler.shutdown()

    asyncio.run(_test())


def test_shutdown_cancels_active_tasks():
    async def _test():
        broker = ProactiveMessageBroker()
        scheduler = ReminderScheduler(
            broker=broker,
            api_key="secret",
            generate_message=lambda task, api_key: task,
        )
        reminder = ParsedReminder(
            remind_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            task="开会",
            confirmation="好",
        )

        assert scheduler.schedule(reminder) is True
        assert scheduler.active_count == 1

        await scheduler.shutdown()

        assert scheduler.active_count == 0

    asyncio.run(_test())
