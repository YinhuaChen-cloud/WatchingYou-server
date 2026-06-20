import asyncio
import time

import pytest

from app.proactive_messages import (
    AUTO_MESSAGE_CONTENT,
    AUTO_MESSAGE_INTERVAL_SECONDS,
    MAX_QUEUE_SIZE,
    POLL_DEFAULT_TIMEOUT_SECONDS,
    POLL_MAX_TIMEOUT_SECONDS,
    POLL_MIN_TIMEOUT_SECONDS,
    ProactiveMessage,
    ProactiveMessageBroker,
    clamp_poll_timeout,
    current_time_millis,
    run_auto_publisher,
)


# ---------------------------------------------------------------------------
# Helper: run async tests without pytest-asyncio
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async test coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# current_time_millis
# ---------------------------------------------------------------------------

class TestCurrentTimeMillis:
    def test_returns_int(self):
        result = current_time_millis()
        assert isinstance(result, int)

    def test_is_reasonably_close_to_now(self):
        now_s = time.time()
        now_ms = current_time_millis()
        assert abs(now_ms - int(now_s * 1000)) <= 5, "should be within 5ms"


# ---------------------------------------------------------------------------
# ProactiveMessage dataclass
# ---------------------------------------------------------------------------

class TestProactiveMessage:
    def test_construction(self):
        msg = ProactiveMessage(content="hello", timestamp=1234567890)
        assert msg.content == "hello"
        assert msg.timestamp == 1234567890

    def test_is_frozen(self):
        msg = ProactiveMessage(content="hello", timestamp=123)
        with pytest.raises(Exception):
            msg.content = "changed"

    def test_to_dict(self):
        msg = ProactiveMessage(content="世界", timestamp=999)
        d = msg.to_dict()
        assert d == {"content": "世界", "timestamp": 999}


# ---------------------------------------------------------------------------
# clamp_poll_timeout
# ---------------------------------------------------------------------------

class TestClampPollTimeout:
    def test_returns_default_when_none(self):
        assert clamp_poll_timeout(None) == POLL_DEFAULT_TIMEOUT_SECONDS

    def test_returns_value_within_range(self):
        assert clamp_poll_timeout(15.5) == 15.5

    def test_clamps_below_minimum(self):
        assert clamp_poll_timeout(0) == POLL_MIN_TIMEOUT_SECONDS
        assert clamp_poll_timeout(0.5) == POLL_MIN_TIMEOUT_SECONDS
        assert clamp_poll_timeout(-5) == POLL_MIN_TIMEOUT_SECONDS

    def test_clamps_above_maximum(self):
        assert clamp_poll_timeout(100) == POLL_MAX_TIMEOUT_SECONDS
        assert clamp_poll_timeout(999) == POLL_MAX_TIMEOUT_SECONDS

    def test_accepts_edge_values(self):
        assert clamp_poll_timeout(POLL_MIN_TIMEOUT_SECONDS) == POLL_MIN_TIMEOUT_SECONDS
        assert clamp_poll_timeout(POLL_MAX_TIMEOUT_SECONDS) == POLL_MAX_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_constants_have_expected_values(self):
        assert AUTO_MESSAGE_INTERVAL_SECONDS == 360
        assert AUTO_MESSAGE_CONTENT == "每隔6min自动发送消息"
        assert POLL_DEFAULT_TIMEOUT_SECONDS == 30
        assert POLL_MIN_TIMEOUT_SECONDS == 1
        assert POLL_MAX_TIMEOUT_SECONDS == 60
        assert MAX_QUEUE_SIZE == 20


# ---------------------------------------------------------------------------
# ProactiveMessageBroker
# ---------------------------------------------------------------------------

class TestProactiveMessageBroker:
    def test_queue_size_defaults_to_max(self):
        broker = ProactiveMessageBroker()
        assert broker.max_queue_size == MAX_QUEUE_SIZE

    def test_queue_size_custom(self):
        broker = ProactiveMessageBroker(max_queue_size=5)
        assert broker.max_queue_size == 5

    def test_poll_returns_message_immediately_when_queued(self):
        async def _test():
            broker = ProactiveMessageBroker(now_ms=lambda: 1000)
            await broker.publish("hello")
            result = await broker.poll()
            assert isinstance(result, ProactiveMessage)
            assert result.content == "hello"
            assert result.timestamp == 1000

        _run(_test())

    def test_publish_generates_timestamp(self):
        async def _test():
            broker = ProactiveMessageBroker(now_ms=lambda: 42)
            await broker.publish("msg")
            result = await broker.poll()
            assert result.timestamp == 42

        _run(_test())

    def test_publish_explicit_timestamp(self):
        async def _test():
            broker = ProactiveMessageBroker()
            await broker.publish("explicit", timestamp_ms=123)
            result = await broker.poll()
            assert result.content == "explicit"
            assert result.timestamp == 123

        _run(_test())

    def test_poll_returns_none_on_timeout(self):
        async def _test():
            broker = ProactiveMessageBroker()
            result = await broker.poll(timeout_seconds=0.05)
            assert result is None

        _run(_test())

    def test_poll_respects_timeout_clamping(self):
        async def _test():
            broker = ProactiveMessageBroker()
            start = time.monotonic()
            result = await broker.poll(timeout_seconds=0.001)
            elapsed = time.monotonic() - start
            assert result is None
            assert elapsed >= 0.5

        _run(_test())

    def test_poll_fifo_order(self):
        async def _test():
            broker = ProactiveMessageBroker()
            await broker.publish("first")
            await broker.publish("second")
            await broker.publish("third")
            assert (await broker.poll()).content == "first"
            assert (await broker.poll()).content == "second"
            assert (await broker.poll()).content == "third"

        _run(_test())

    def test_publish_beyond_max_drops_oldest(self):
        async def _test():
            broker = ProactiveMessageBroker(max_queue_size=3)
            await broker.publish("a")
            await broker.publish("b")
            await broker.publish("c")
            await broker.publish("d")  # drops "a"
            assert (await broker.poll()).content == "b"
            assert (await broker.poll()).content == "c"
            assert (await broker.poll()).content == "d"
            result = await broker.poll(timeout_seconds=0.05)
            assert result is None

        _run(_test())

    def test_multiple_waiters_all_woken(self):
        async def _test():
            broker = ProactiveMessageBroker()

            async def waiter():
                return await broker.poll(timeout_seconds=5)

            task1 = asyncio.create_task(waiter())
            task2 = asyncio.create_task(waiter())
            await asyncio.sleep(0.1)
            await broker.publish("msg")
            results = await asyncio.gather(task1, task2)
            content_results = [
                r.content if isinstance(r, ProactiveMessage) else None for r in results
            ]
            assert content_results.count("msg") == 1
            assert content_results.count(None) == 1

        _run(_test())

    def test_poll_with_default_timeout_uses_30_seconds(self):
        async def _test():
            broker = ProactiveMessageBroker()

            async def delayed_publish():
                await asyncio.sleep(0.1)
                await broker.publish("delayed")

            asyncio.create_task(delayed_publish())
            start = time.monotonic()
            result = await broker.poll()
            elapsed = time.monotonic() - start
            assert isinstance(result, ProactiveMessage)
            assert result.content == "delayed"
            assert elapsed < 1.0

        _run(_test())


# ---------------------------------------------------------------------------
# run_auto_publisher
# ---------------------------------------------------------------------------

class TestRunAutoPublisher:
    def test_publishes_after_interval_not_immediately(self):
        async def _test():
            broker = ProactiveMessageBroker()
            stop_event = asyncio.Event()
            task = asyncio.create_task(
                run_auto_publisher(broker, interval_seconds=0.1, stop_event=stop_event)
            )

            start = time.monotonic()
            result = await broker.poll(timeout_seconds=3)
            elapsed = time.monotonic() - start

            assert isinstance(result, ProactiveMessage)
            assert result.content == AUTO_MESSAGE_CONTENT
            assert isinstance(result.timestamp, int)
            # Message should arrive at roughly the interval (0.1s), not immediately after 3s
            assert elapsed < 2.0, f"message took too long: {elapsed}s"

            stop_event.set()
            await task

        _run(_test())

    def test_publishes_repeatedly(self):
        async def _test():
            broker = ProactiveMessageBroker()
            stop_event = asyncio.Event()
            task = asyncio.create_task(
                run_auto_publisher(broker, interval_seconds=0.05, stop_event=stop_event)
            )
            messages = []
            for _ in range(3):
                msg = await broker.poll(timeout_seconds=0.2)
                if msg is not None:
                    messages.append(msg)
            assert len(messages) >= 2, f"Expected at least 2, got {len(messages)}"
            for msg in messages:
                assert isinstance(msg, ProactiveMessage)
                assert msg.content == AUTO_MESSAGE_CONTENT
                assert isinstance(msg.timestamp, int)
            stop_event.set()
            await task

        _run(_test())

    def test_stop_event_exits_cleanly(self):
        async def _test():
            broker = ProactiveMessageBroker()
            stop_event = asyncio.Event()
            task = asyncio.create_task(
                run_auto_publisher(broker, interval_seconds=0.05, stop_event=stop_event)
            )
            await asyncio.sleep(0.1)
            stop_event.set()
            await asyncio.wait_for(task, timeout=1.0)

        _run(_test())

    def test_stop_event_none_runs_indefinitely(self):
        async def _test():
            broker = ProactiveMessageBroker()
            task = asyncio.create_task(
                run_auto_publisher(broker, interval_seconds=0.05, stop_event=None)
            )
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            msg = await broker.poll(timeout_seconds=0.05)
            assert isinstance(msg, ProactiveMessage)
            assert msg.content == AUTO_MESSAGE_CONTENT

        _run(_test())

    def test_default_interval_is_360_seconds(self):
        async def _test():
            broker = ProactiveMessageBroker()
            stop_event = asyncio.Event()
            task = asyncio.create_task(
                run_auto_publisher(broker, stop_event=stop_event)
            )
            result = await broker.poll(timeout_seconds=0.1)
            assert result is None, "should not publish within 360s interval in 0.1s"
            stop_event.set()
            await task

        _run(_test())