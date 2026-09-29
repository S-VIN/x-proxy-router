"""Run with python -m server.main from the project root."""

import asyncio
import json
import logging
import signal
import sqlite3
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC
from functools import partial
from inspect import iscoroutinefunction
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import WSCloseCode, WSMsgType, web
from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN
from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .cores.mihomo.mihomo_client import MihomoClient
from .handlers.core import connect_best_outbound_server, register_outbound_servers
from .handlers.init import init
from .handlers.outbound_test import test_outbound_servers
from .handlers.reg_filter import add_reg_filter, delete_reg_filter
from .handlers.requests import (
    request_connect_outbound_server,
    request_refresh_subscriptions,
    request_test_outbound_servers,
)
from .handlers.server_settings import change_server_settings
from .handlers.subscription_link import (
    add_subscription_link,
    change_subscription_link,
    delete_subscription_link,
)
from .handlers.subscriptions import schedule_refresh_subscriptions
from .model_sync import ModelChannel, ModelSync
from .models.application_context import ApplicationContext
from .models.serialization import JsonValue
from .request_error import ErrorCode, RequestError
from .settings_store import SettingsStore
from .static_files import add_static_routes
from .tasks import TaskCancelled, TaskRegistry

log = logging.getLogger(__name__)

# SOCKS5 listeners of the core on 127.0.0.1: the main route for traffic and
# the test route for server checks.
PROXY_PORT = 20808
TEST_PORT = 20809

# Clients connect to ws://WEBSOCKET_HOST:WEBSOCKET_PORT/ws (server/PROTOCOL.md).
WEBSOCKET_HOST = "127.0.0.1"
WEBSOCKET_PORT: int = 20800
WEBSOCKET_PATH = "/ws"
# Browser origins allowed besides http(s) pages on localhost, e.g. "app://x-proxy-router".
WEBSOCKET_ALLOWED_ORIGINS: frozenset[str] = frozenset()
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# Seconds between pings; a client that does not answer is disconnected.
WEBSOCKET_HEARTBEAT = 30.0
WEBSOCKET_MAX_MESSAGE_SIZE = 1024 * 1024
# The built web client (npm run build in web/), served at http://WEBSOCKET_HOST:WEBSOCKET_PORT/;
# None serves only the WebSocket.
WEB_CLIENT_DIR: Path | None = Path(__file__).resolve().parent.parent / "web" / "dist"


def origin_allowed(origin: str | None) -> bool:
    """Whether a WebSocket connection with this Origin header may control the server.

    Browsers let any page connect to a local WebSocket and send the page's origin,
    so only local pages are accepted. Clients that are not browsers (the Electron
    main process, scripts) send no Origin and are accepted.
    """
    if origin is None:
        return True
    if origin in WEBSOCKET_ALLOWED_ORIGINS:
        return True
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.hostname in _LOCAL_HOSTS


AsyncHandler = Callable[[], Awaitable[object]]


class Scheduler:
    """Keep async handlers on the application loop, including SQLite access.

    Triggers and time calculations belong to APScheduler. This adapter waits for
    active handlers before shutdown, while settings and the core are still usable.
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler(
            timezone=UTC, job_defaults={"coalesce": True, "max_instances": 1}
        )
        self._active: set[asyncio.Task] = set()
        self._stopping = False

    def start(self) -> None:
        self._stopping = False
        self._scheduler.start()

    def add_job(self, handler: AsyncHandler, trigger: BaseTrigger, *, id: str) -> Job:
        """Attach an async function, bound method or partial to a schedule."""
        if not iscoroutinefunction(handler):
            raise TypeError("Scheduled handlers must be async functions")
        return self._scheduler.add_job(
            self._execute, trigger=trigger, id=id, name=id, args=(handler,)
        )

    def get_job(self, id: str) -> Job | None:
        """The scheduled job with this id, or None."""
        return self._scheduler.get_job(id)

    def reschedule_job(self, id: str, trigger: BaseTrigger) -> Job:
        """Change future runs of a job without restarting an active handler."""
        return self._scheduler.reschedule_job(id, trigger=trigger)

    def remove_job(self, id: str) -> None:
        """Remove future runs; a handler already running may finish."""
        self._scheduler.remove_job(id)

    async def _execute(self, handler: AsyncHandler) -> object:
        if self._stopping:
            return None
        task = asyncio.current_task()
        assert task is not None
        self._active.add(task)
        try:
            return await handler()
        except TaskCancelled as error:
            # Stopped on purpose by another task; the next run follows the schedule.
            log.info("%s", error)
            return None
        finally:
            self._active.discard(task)

    async def stop(self) -> None:
        """Stop scheduling and await active jobs. Called by application shutdown."""
        if asyncio.current_task() in self._active:
            raise RuntimeError("Stop the scheduler from the application, not a scheduled handler")
        if not self._scheduler.running:
            return
        self._stopping = True
        self._scheduler.pause()
        await asyncio.gather(*self._active, return_exceptions=True)
        stopped = asyncio.Event()

        def on_shutdown(event) -> None:
            stopped.set()

        self._scheduler.add_listener(on_shutdown, EVENT_SCHEDULER_SHUTDOWN)
        try:
            self._scheduler.shutdown(wait=False)
            await stopped.wait()
        finally:
            self._scheduler.remove_listener(on_shutdown)


RequestPayload = dict[str, JsonValue]
RequestHandler = Callable[[RequestPayload], Awaitable[RequestPayload]]
# Writes one text frame; provided by the transport for each connection.
FrameSender = Callable[[str], Awaitable[None]]
ConnectListener = Callable[[str], None]


class WebSocketServer:
    """Answer client requests and queue outgoing JSON for each connection.

    A request is {"type", "model", "request_id", "payload"}; the handler registered
    for (type, model) runs in its own task and exactly one response is queued:
    {"type": "response", "model", "request_id", "ok", "payload"[, "error"]}.
    Handlers are ordinary async callables; registration does not wrap them.

    start() serves WebSocket connections with aiohttp: each socket is connected
    with connect(), its text frames go to receive(), and disconnect() runs when
    it closes. connect(), receive() and disconnect() also work without the
    network, e.g. in tests.
    """

    def __init__(self):
        self._handlers: dict[tuple[str, str], RequestHandler] = {}
        self._connections: dict[str, tuple[asyncio.Queue[str], asyncio.Task]] = {}
        self._connect_listeners: list[ConnectListener] = []
        self._requests: set[asyncio.Task] = set()
        self._runner: web.AppRunner | None = None
        self._sockets: set[web.WebSocketResponse] = set()
        # The listening port while started; useful when started on port 0.
        self.port: int | None = None

    def register(self, request_type: str, model: str, handler: RequestHandler) -> None:
        if not request_type or not model:
            raise ValueError("Request type and model must not be empty")
        if (request_type, model) in self._handlers:
            raise ValueError("A handler is already registered for this request")
        self._handlers[request_type, model] = handler

    async def dispatch(
        self, request_type: str, model: str, payload: RequestPayload
    ) -> RequestPayload:
        """Invoke a handler locally. Unknown requests raise RequestError."""
        handler = self._handlers.get((request_type, model))
        if handler is None:
            raise RequestError(
                ErrorCode.UNKNOWN_REQUEST, f"Unknown request {request_type} for {model}"
            )
        return await handler(payload)

    def receive(self, connection_id: str, frame: str) -> None:
        """Handle one text frame from a connection; the response is queued later.

        Unknown connection ids raise KeyError.
        """
        if connection_id not in self._connections:
            raise KeyError(connection_id)
        try:
            message = json.loads(frame)
        except ValueError:
            message = None
        if not isinstance(message, dict):
            error = RequestError(ErrorCode.BAD_REQUEST, "Message must be a JSON object")
            self._respond(connection_id, None, None, error=error)
            return
        # Well-formed identifiers are echoed even when the rest of the message is invalid.
        request_id, request_type, model = (
            value if isinstance(value := message.get(name), str) and value else None
            for name in ("request_id", "type", "model")
        )
        payload = message.get("payload")
        if request_id is None or request_type is None or model is None:
            error = RequestError(
                ErrorCode.BAD_REQUEST, "Fields request_id, type and model must be non-empty strings"
            )
            self._respond(connection_id, model, request_id, error=error)
            return
        if not isinstance(payload, dict):
            error = RequestError(ErrorCode.BAD_REQUEST, "Field payload must be an object")
            self._respond(connection_id, model, request_id, error=error)
            return
        task = asyncio.create_task(
            self._handle(connection_id, request_type, model, request_id, payload),
            name=f"websocket-request-{request_id}",
        )
        self._requests.add(task)
        task.add_done_callback(self._requests.discard)

    async def _handle(
        self,
        connection_id: str,
        request_type: str,
        model: str,
        request_id: str,
        payload: RequestPayload,
    ) -> None:
        try:
            result = await self.dispatch(request_type, model, payload)
        except RequestError as error:
            self._respond(connection_id, model, request_id, error=error)
        except TaskCancelled as error:
            error = RequestError(ErrorCode.CANCELLED, str(error))
            self._respond(connection_id, model, request_id, error=error)
        except ValueError as error:
            # Models raise ValueError with messages meant for users, e.g. an invalid URL.
            error = RequestError(ErrorCode.VALIDATION_ERROR, str(error))
            self._respond(connection_id, model, request_id, error=error)
        except sqlite3.IntegrityError:
            error = RequestError(ErrorCode.CONFLICT, "The change conflicts with existing data")
            self._respond(connection_id, model, request_id, error=error)
        except Exception:
            # Exception text may contain secrets such as subscription URLs; log it only.
            log.exception("Request %s %s failed", request_type, model)
            error = RequestError(ErrorCode.INTERNAL_ERROR, "Internal server error")
            self._respond(connection_id, model, request_id, error=error)
        else:
            self._respond(connection_id, model, request_id, result=result)

    def _respond(
        self,
        connection_id: str,
        model: str | None,
        request_id: str | None,
        *,
        result: RequestPayload | None = None,
        error: RequestError | None = None,
    ) -> None:
        # The client may have disconnected while the handler was running.
        if connection_id not in self._connections:
            return
        response: dict[str, JsonValue] = {
            "type": "response",
            "model": model,
            "request_id": request_id,
            "ok": error is None,
            "payload": result if result is not None else {},
        }
        if error is not None:
            response["error"] = {
                "code": error.code.value,
                "message": error.message,
                "details": error.details,
            }
        self.send(connection_id, response)

    def add_connect_listener(self, listener: ConnectListener) -> None:
        """Call listener(connection_id) for each new connection, e.g. to send initial data."""
        self._connect_listeners.append(listener)

    def connect(self, connection_id: str, send: FrameSender) -> None:
        """Start the connection's writer, then let listeners queue initial messages."""
        if connection_id in self._connections:
            raise ValueError("Connection id is already in use")
        queue: asyncio.Queue[str] = asyncio.Queue()
        writer = asyncio.create_task(
            self._write(connection_id, queue, send), name=f"websocket-{connection_id}"
        )
        self._connections[connection_id] = (queue, writer)
        try:
            for listener in self._connect_listeners:
                listener(connection_id)
        except BaseException:
            del self._connections[connection_id]
            writer.cancel()
            raise

    async def disconnect(self, connection_id: str) -> None:
        """Stop writing to a connection; unsent messages are dropped.

        Requests already received still run to completion, without a response.
        """
        connection = self._connections.pop(connection_id, None)
        if connection is not None:
            connection[1].cancel()
            await asyncio.gather(connection[1], return_exceptions=True)

    async def close(self) -> None:
        """Stop the transport, cancel running requests and close all connections.

        Called at application shutdown.
        """
        await self.stop()
        requests = list(self._requests)
        for task in requests:
            task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
        for connection_id in list(self._connections):
            await self.disconnect(connection_id)

    async def _write(self, connection_id: str, queue: asyncio.Queue[str], send: FrameSender):
        try:
            while True:
                await send(await queue.get())
        except Exception:  # noqa: BLE001 - a transport error closes only this connection
            log.warning("Closing WebSocket connection %s after a send error", connection_id)
            self._connections.pop(connection_id, None)

    def send(self, connection_id: str, message: JsonValue) -> None:
        """Queue a message for one connection; unknown ids raise KeyError.

        Messages to one connection are written in the order they were queued.
        """
        self._connections[connection_id][0].put_nowait(json.dumps(message))

    def broadcast(self, message: JsonValue, *, exclude: str | None = None) -> None:
        """Queue a message for all current connections except `exclude`."""
        frame = json.dumps(message)
        for connection_id, (queue, _) in self._connections.items():
            if connection_id != exclude:
                queue.put_nowait(frame)

    async def start(self, host: str, port: int, *, static_dir: Path | None = None) -> None:
        """Listen for WebSocket connections at ws://host:port/ws; port 0 picks a free one.

        With static_dir, files from it are also served over HTTP at the other paths.
        """
        if self._runner is not None:
            raise RuntimeError("The WebSocket server is already started")
        app = web.Application()
        app.router.add_get(WEBSOCKET_PATH, self._serve)
        if static_dir is not None:
            add_static_routes(app, static_dir)
        # Runs after the listener stops and before open handlers are awaited.
        app.on_shutdown.append(self._close_sockets)
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=5)
        await runner.setup()
        try:
            await web.TCPSite(runner, host, port).start()
        except BaseException:
            await runner.cleanup()
            raise
        self._runner = runner
        self.port = runner.addresses[0][1]
        log.info("WebSocket server listening on ws://%s:%s%s", host, self.port, WEBSOCKET_PATH)
        if static_dir is not None:
            log.info("Web client available at http://%s:%s/", host, self.port)

    async def stop(self) -> None:
        """Stop listening and close open sockets with code 1001 (going away)."""
        runner, self._runner = self._runner, None
        if runner is not None:
            await runner.cleanup()
            self.port = None

    async def _close_sockets(self, app: web.Application) -> None:
        for socket in list(self._sockets):
            await socket.close(code=WSCloseCode.GOING_AWAY, message=b"Server shutdown")

    async def _serve(self, request: web.Request) -> web.StreamResponse:
        """One WebSocket connection: text frames are requests, sent messages go out."""
        origin = request.headers.get("Origin")
        if not origin_allowed(origin):
            log.warning("Rejected WebSocket connection from origin %s", origin)
            return web.Response(status=403, text="Origin is not allowed")
        socket = web.WebSocketResponse(
            heartbeat=WEBSOCKET_HEARTBEAT, max_msg_size=WEBSOCKET_MAX_MESSAGE_SIZE
        )
        await socket.prepare(request)
        connection_id = uuid4().hex
        self._sockets.add(socket)
        try:
            self.connect(connection_id, socket.send_str)
            async for message in socket:
                # The writer drops the connection when a send fails.
                if connection_id not in self._connections:
                    break
                if message.type == WSMsgType.TEXT:
                    self.receive(connection_id, message.data)
                elif message.type == WSMsgType.BINARY:
                    await socket.close(
                        code=WSCloseCode.UNSUPPORTED_DATA, message=b"Only text frames are accepted"
                    )
        finally:
            self._sockets.discard(socket)
            await self.disconnect(connection_id)
            await socket.close()
        return socket


@asynccontextmanager
async def application() -> AsyncIterator[ApplicationContext]:
    """Create shared services; stop jobs and the core before closing SQLite.

    The core is started and the stored servers are registered in it before the
    application is ready; if the core cannot start, the application does not start.
    With auto_connect on, the best stored server is connected then as well.
    """
    with SettingsStore() as settings:
        core_client = MihomoClient()
        scheduler = Scheduler()
        websocket = WebSocketServer()
        sync = ModelSync(websocket)
        sync.register(ModelChannel("server_settings", lambda: [settings.server_settings.get()]))
        sync.register(ModelChannel("subscription_link", settings.subscription_link.get_all))
        sync.register(ModelChannel("reg_filter", settings.reg_filter.get_all))
        sync.register(ModelChannel("outbound_server", settings.outbound_server.get_all))
        tasks = TaskRegistry(on_change=partial(sync.notify, "task"))
        sync.register(ModelChannel("task", tasks.states))
        context = ApplicationContext(settings, core_client, scheduler, websocket, sync, tasks=tasks)
        init_task = None
        try:
            scheduler.start()
            await core_client.service_start(PROXY_PORT, TEST_PORT)
            await register_outbound_servers(context)
            await connect_best_outbound_server(context)
            await websocket.start(WEBSOCKET_HOST, WEBSOCKET_PORT, static_dir=WEB_CLIENT_DIR)
            init_task = asyncio.create_task(init(context), name="application-init")
            yield context
        finally:
            try:
                if init_task is not None:
                    init_task.cancel()
                    await asyncio.gather(init_task, return_exceptions=True)
                # Long tasks outlive their callers, so they are stopped explicitly.
                await context.tasks.cancel_all()
            finally:
                try:
                    await websocket.close()
                    await scheduler.stop()
                finally:
                    await core_client.service_stop()


def configure_handlers(context: ApplicationContext) -> None:
    """Register application schedules and client request handlers here.

    See README.md for interval, cron, one-shot schedules and WebSocket
    registration using ordinary async functions.
    """
    # Every subscription_refresh_interval seconds; init refreshes once at startup.
    schedule_refresh_subscriptions(context)
    # The first run is an hour after startup.
    context.scheduler.add_job(
        partial(test_outbound_servers, context),
        IntervalTrigger(hours=1),
        id="test_outbound_servers",
    )
    websocket = context.websocket
    websocket.register("add", "subscription_link", partial(add_subscription_link, context))
    websocket.register("change", "subscription_link", partial(change_subscription_link, context))
    websocket.register("delete", "subscription_link", partial(delete_subscription_link, context))
    websocket.register("add", "reg_filter", partial(add_reg_filter, context))
    websocket.register("delete", "reg_filter", partial(delete_reg_filter, context))
    websocket.register("change", "server_settings", partial(change_server_settings, context))
    websocket.register(
        "request", "refresh_subscriptions", partial(request_refresh_subscriptions, context)
    )
    websocket.register(
        "request", "test_outbound_servers", partial(request_test_outbound_servers, context)
    )
    websocket.register(
        "request", "connect_outbound_server", partial(request_connect_outbound_server, context)
    )


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(signum, frame) -> None:
        loop.call_soon_threadsafe(stop.set)

    # signal.signal also works on Windows, unlike loop.add_signal_handler.
    # SIGHUP (POSIX only) comes when the terminal running the server closes.
    signums = [signal.SIGINT, signal.SIGTERM]
    if sys.platform != "win32":
        signums.append(signal.SIGHUP)
    previous_handlers = {signum: signal.signal(signum, request_stop) for signum in signums}
    try:
        async with application() as context:
            configure_handlers(context)
            log.info("Application started")
            await stop.wait()
        log.info("Application stopped")
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(main())
