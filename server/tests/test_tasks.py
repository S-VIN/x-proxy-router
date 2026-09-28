import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from apscheduler.triggers.date import DateTrigger

from server import tasks as tasks_module
from server.main import Scheduler, WebSocketServer
from server.models import TaskState, TaskStatus
from server.tasks import TaskCancelled, TaskRegistry, long_task
from server.tests.test_requests import Client


class LongTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Tasks declared here must not show up in other tests' snapshots.
        self.enterContext(patch.object(tasks_module, "_declared", set()))
        self.context: Any = SimpleNamespace(tasks=TaskRegistry())
        self.started: list[str] = []
        self.release = asyncio.Event()

        @long_task("slow")
        async def slow(context, value):
            self.started.append(f"slow:{value}")
            await self.release.wait()
            return value

        @long_task("canceller", cancels=["slow"])
        async def canceller(context):
            self.started.append("canceller")
            return "done"

        @long_task("polite", skip_while=["slow"])
        async def polite(context):
            self.started.append("polite")
            return "ran"

        self.slow, self.canceller, self.polite = slow, canceller, polite

    async def settle(self):
        for _ in range(5):
            await asyncio.sleep(0)

    async def test_second_call_joins_the_running_task(self):
        first = asyncio.create_task(self.slow(self.context, 1))
        await self.settle()
        second = asyncio.create_task(self.slow(self.context, 2))
        await self.settle()
        self.assertTrue(self.context.tasks.running("slow"))
        self.release.set()
        # Both callers get the running task's result; no second run started.
        self.assertEqual(await asyncio.gather(first, second), [1, 1])
        self.assertEqual(self.started, ["slow:1"])
        self.assertFalse(self.context.tasks.running("slow"))
        # Once finished, the name is free again.
        self.assertEqual(await self.slow(self.context, 3), 3)

    async def test_cancels_stops_the_other_task_first(self):
        first = asyncio.create_task(self.slow(self.context, 1))
        await self.settle()
        self.assertEqual(await self.canceller(self.context), "done")
        with self.assertRaises(TaskCancelled) as raised:
            await first
        self.assertEqual(raised.exception.name, "slow")
        self.assertEqual(self.started, ["slow:1", "canceller"])
        self.assertFalse(self.context.tasks.running("slow"))
        # Nothing to cancel: runs at once.
        self.assertEqual(await self.canceller(self.context), "done")

    async def test_skip_while(self):
        self.assertEqual(await self.polite(self.context), "ran")
        running = asyncio.create_task(self.slow(self.context, 1))
        await self.settle()
        self.assertIsNone(await self.polite(self.context))
        self.assertEqual(self.started, ["polite", "slow:1"])
        self.release.set()
        await running

    async def test_cancelled_caller_does_not_stop_the_task(self):
        caller = asyncio.create_task(self.slow(self.context, 1))
        await self.settle()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertTrue(self.context.tasks.running("slow"))
        waiter = asyncio.create_task(self.context.tasks.wait("slow"))
        await self.settle()
        self.assertFalse(waiter.done())
        self.release.set()
        await waiter
        self.assertFalse(self.context.tasks.running("slow"))

    async def test_errors_reach_every_caller_and_free_the_name(self):
        @long_task("failing")
        async def failing(context):
            await self.release.wait()
            raise ValueError("broken")

        callers = [asyncio.create_task(failing(self.context)) for _ in range(2)]
        await self.settle()
        self.release.set()
        for caller in callers:
            with self.assertRaisesRegex(ValueError, "broken"):
                await caller
        self.assertFalse(self.context.tasks.running("failing"))

    async def test_cancel_all_wait_and_idle_names(self):
        tasks = self.context.tasks
        await tasks.cancel("missing")
        await tasks.wait("missing")
        running = asyncio.create_task(self.slow(self.context, 1))
        await self.settle()
        await tasks.cancel_all()
        with self.assertRaises(TaskCancelled):
            await running
        self.assertFalse(tasks.running("slow"))

    async def test_states_and_change_notifications(self):
        on_change = AsyncMock()
        self.context.tasks = TaskRegistry(on_change=on_change)
        stopped = [
            TaskState(id=name, status=TaskStatus.STOPPED)
            for name in ("canceller", "polite", "slow")
        ]
        # Declared tasks are listed even when they are not running.
        self.assertEqual(self.context.tasks.states(), stopped)
        running = asyncio.create_task(self.slow(self.context, 1))
        await self.settle()
        on_change.assert_awaited_once()
        self.assertEqual(
            self.context.tasks.states()[-1], TaskState(id="slow", status=TaskStatus.RUNNING)
        )
        # Joining the running task changes nothing.
        joined = asyncio.create_task(self.slow(self.context, 2))
        await self.settle()
        self.assertEqual(on_change.await_count, 1)
        self.release.set()
        await asyncio.gather(running, joined)
        self.assertEqual(on_change.await_count, 2)
        self.assertEqual(self.context.tasks.states(), stopped)
        # A skipped call does not start, so it is not reported.
        blocker = asyncio.create_task(self.context.tasks.run("slow", asyncio.Event().wait))
        await self.settle()
        self.assertIsNone(await self.polite(self.context))
        self.assertEqual(on_change.await_count, 3)
        await self.context.tasks.cancel("slow")
        self.assertEqual(on_change.await_count, 4)
        with self.assertRaises(TaskCancelled):
            await blocker

    async def test_undeclared_running_task_is_listed(self):
        registry = TaskRegistry()
        running = asyncio.create_task(registry.run("adhoc", asyncio.Event().wait))
        await self.settle()
        self.assertIn(TaskState(id="adhoc", status=TaskStatus.RUNNING), registry.states())
        await registry.cancel("adhoc")
        with self.assertRaises(TaskCancelled):
            await running
        self.assertNotIn("adhoc", [state.id for state in registry.states()])

    async def test_task_cannot_cancel_itself(self):
        @long_task("self")
        async def itself(context):
            await context.tasks.cancel("self")

        with self.assertRaises(RuntimeError):
            await itself(self.context)


class TaskCancelledHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_job_is_not_reported_as_failure(self):
        scheduler = Scheduler()
        scheduler.start()
        self.addAsyncCleanup(scheduler.stop)
        finished = asyncio.Event()

        async def cancelled():
            finished.set()
            raise TaskCancelled("example")

        with self.assertLogs("server.main", level="INFO") as logs:
            scheduler.add_job(cancelled, DateTrigger(run_date=datetime.now(UTC)), id="job")
            await asyncio.wait_for(finished.wait(), 2)
            for _ in range(5):
                await asyncio.sleep(0)
        self.assertEqual([record.levelname for record in logs.records], ["INFO"])

    async def test_request_gets_cancelled_error(self):
        websocket = WebSocketServer()
        self.addAsyncCleanup(websocket.close)
        client = Client(websocket)

        async def cancelled(payload):
            raise TaskCancelled("refresh_subscriptions")

        websocket.register("request", "example", cancelled)
        error = await client.error("request", "example", {})
        self.assertEqual(
            error,
            {
                "code": "cancelled",
                "message": "Task refresh_subscriptions was cancelled",
                "details": {},
            },
        )
