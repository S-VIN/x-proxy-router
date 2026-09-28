"""Long tasks: named handlers that can be found and stopped by other handlers.

    @long_task("refresh_subscriptions", cancels=["test_outbound_servers"])
    async def refresh_subscriptions(context: ApplicationContext) -> None: ...

The decorated function is called as before: directly, from a request handler
or from the scheduler. Its first argument must be the ApplicationContext.
Clients see every declared task and whether it is running (the "task" model).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar

from .models.task_state import TaskState, TaskStatus

if TYPE_CHECKING:
    from .models.application_context import ApplicationContext

log = logging.getLogger(__name__)

# Names given to @long_task; filled when handler modules are imported.
_declared: set[str] = set()

P = ParamSpec("P")
R = TypeVar("R")


class TaskCancelled(Exception):
    """The long task was stopped by another task or by application shutdown."""

    def __init__(self, name: str):
        super().__init__(f"Task {name} was cancelled")
        self.name = name


class TaskRegistry:
    """Running long tasks by name; at most one task runs under each name.

    A task runs in its own asyncio task: cancelling a caller (for example, a
    disconnected client's request) does not stop it, only cancel() does.
    """

    def __init__(self, on_change: Callable[[], Awaitable[object]] | None = None):
        """on_change is awaited after a task starts or finishes, e.g. to notify clients."""
        self._running: dict[str, asyncio.Task[Any]] = {}
        self._on_change = on_change

    def running(self, name: str) -> bool:
        return name in self._running

    def states(self) -> list[TaskState]:
        """Every declared task and any other running one, sorted by name."""
        return [
            TaskState(
                id=name,
                status=TaskStatus.RUNNING if name in self._running else TaskStatus.STOPPED,
            )
            for name in sorted(_declared | self._running.keys())
        ]

    async def _changed(self) -> None:
        if self._on_change is not None:
            await self._on_change()

    async def run(
        self,
        name: str,
        start: Callable[[], Awaitable[R]],
        *,
        cancels: Iterable[str] = (),
        skip_while: Iterable[str] = (),
    ) -> R | None:
        """Run start() as the task `name` and return its result.

        - A task from skip_while is running: nothing starts, returns None.
        - `name` is already running: nothing new starts; the caller waits for
          the running one and gets its result or error.
        - Otherwise the tasks from `cancels` are stopped first, then start() runs.

        TaskCancelled is raised if the task is stopped by cancel().
        """
        if blocking := [other for other in skip_while if other in self._running]:
            log.info("Task %s is skipped while %s is running", name, blocking[0])
            return None
        task = self._running.get(name)
        if task is None:

            async def body() -> R:
                try:
                    await self._changed()
                    for other in cancels:
                        await self.cancel(other)
                    return await start()
                finally:
                    # Inside the task, so the name is free once the task is done.
                    if self._running.get(name) is task:
                        del self._running[name]
                    await self._changed()

            # Registered before the first await, so a second call sees it.
            task = asyncio.create_task(body(), name=f"long-task:{name}")
            self._running[name] = task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise  # The caller itself was cancelled; the task goes on.
            raise TaskCancelled(name) from None

    async def cancel(self, name: str) -> None:
        """Stop the task if it is running and wait until it has finished."""
        task = self._running.get(name)
        if task is None:
            return
        if task is asyncio.current_task():
            raise RuntimeError(f"Task {name} cannot cancel itself")
        task.cancel()
        await asyncio.wait([task])

    async def cancel_all(self) -> None:
        """Stop every running task; called on application shutdown."""
        await asyncio.gather(*(self.cancel(name) for name in list(self._running)))

    async def wait(self, name: str) -> None:
        """Wait until the running task finishes, however it ends; no-op if idle."""
        task = self._running.get(name)
        if task is not None:
            await asyncio.wait([task])


def long_task(
    name: str, *, cancels: Iterable[str] = (), skip_while: Iterable[str] = ()
) -> Callable[
    [Callable[Concatenate[ApplicationContext, P], Awaitable[R]]],
    Callable[Concatenate[ApplicationContext, P], Coroutine[Any, Any, R | None]],
]:
    """Make an async handler a long task registered in context.tasks; see TaskRegistry.run."""
    cancels, skip_while = tuple(cancels), tuple(skip_while)
    _declared.add(name)

    def decorate(
        function: Callable[Concatenate[ApplicationContext, P], Awaitable[R]],
    ) -> Callable[Concatenate[ApplicationContext, P], Coroutine[Any, Any, R | None]]:
        @wraps(function)
        async def wrapper(
            context: ApplicationContext, *args: P.args, **kwargs: P.kwargs
        ) -> R | None:
            return await context.tasks.run(
                name,
                lambda: function(context, *args, **kwargs),
                cancels=cancels,
                skip_while=skip_while,
            )

        return wrapper

    return decorate
