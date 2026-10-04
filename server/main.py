"""Run with python -m server.main from the project root, with the environment from README.md."""

import asyncio
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC
from functools import partial
from inspect import iscoroutinefunction
from ipaddress import ip_address
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
from .handlers.auto_connect import (
    RETRY_INTERVAL,
    AutoConnectState,
    on_servers_changed,
    watch_connected_server,
)
from .handlers.core import register_outbound_servers
from .handlers.inbound_server import (
    add_inbound_server,
    change_inbound_server,
    delete_inbound_server,
    start_inbound_servers,
)
from .handlers.init import init
from .handlers.outbound_test import (
    add_outbound_test,
    delete_outbound_test,
    test_outbound_servers,
)
from .handlers.reg_filter import add_reg_filter, delete_reg_filter
from .handlers.requests import (
    request_connect_outbound_server,
    request_refresh_subscriptions,
    request_test_outbound_servers,
)
from .handlers.routing_rule import (
    add_routing_rule,
    apply_routing_rules,
    change_routing_rule,
    delete_routing_rule,
)
from .handlers.server_settings import change_server_settings
from .handlers.subscription_link import (
    add_subscription_link,
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

# Clients connect to ws://WEBSOCKET_HOST:WEBSOCKET_PORT/ws (server/PROTOCOL.md).
# Running main.py takes them from XPR_UI_HOST and XPR_UI_PORT (read_environment).
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
# The folder of settings.sqlite3; running main.py takes it from XPR_DATA_DIR.
# None is the working directory, e.g. in tests.
DATA_DIR: Path | None = None


def read_environment(environ: Mapping[str, str]) -> tuple[str, int, Path]:
    """Host and port of the web interface and the data folder for running main.py.

    XPR_UI_PORT and XPR_DATA_DIR (an absolute path) are required; XPR_UI_HOST is an
    IP address or localhost, 0.0.0.0 when not set. The desktop application and Docker
    set them. Missing or invalid values raise ValueError naming each of them.
    """
    errors = []
    host = environ.get("XPR_UI_HOST", "").strip() or "0.0.0.0"
    if host != "localhost":
        try:
            ip_address(host)
        except ValueError:
            errors.append(
                f"XPR_UI_HOST must be an IP address, e.g. 0.0.0.0 or 127.0.0.1, not {host!r}"
            )
    value = environ.get("XPR_UI_PORT", "").strip()
    port = int(value) if value.isdecimal() else 0
    if not value:
        errors.append("Set XPR_UI_PORT, the port of the web interface, e.g. 20800")
    elif not 1 <= port <= 65535:
        errors.append(f"XPR_UI_PORT must be a port from 1 to 65535, not {value!r}")
    directory = environ.get("XPR_DATA_DIR", "").strip()
    if not directory:
        errors.append("Set XPR_DATA_DIR, the folder for the settings (settings.sqlite3)")
    elif not Path(directory).is_absolute():
        errors.append(f"XPR_DATA_DIR must be an absolute path, not {directory!r}")
    if errors:
        raise ValueError("\n".join(errors))
    return host, port, Path(directory)


def stops_with_stdin(environ: Mapping[str, str]) -> bool:
    """Whether XPR_STOP_ON_STDIN_CLOSE=1 asks to stop when standard input closes.

    The desktop application sets it and keeps a pipe to standard input: it closes
    the pipe to stop the server, and the pipe closes by itself if the application
    dies. Windows has no signal that would let the server stop in order.
    """
    return environ.get("XPR_STOP_ON_STDIN_CLOSE", "").strip() == "1"


def is_loopback(host: str) -> bool:
    """Whether a listener on host is reachable only from this computer."""
    try:
        return host == "localhost" or ip_address(host).is_loopback
    except ValueError:
        return False


def origin_allowed(origin: str | None, host: str | None = None) -> bool:
    """Whether a WebSocket connection with this Origin header may control the server.

    Browsers let any page connect to a local WebSocket and send the page's origin,
    so only local pages are accepted. Clients that are not browsers (the Electron
    main process, scripts) send no Origin and are accepted.

    host is the Host header of a request to a server open to the network: its own
    pages are accepted at any address it is opened at, e.g. http://192.168.1.2:20800.
    """
    if origin is None:
        return True
    if origin in WEBSOCKET_ALLOWED_ORIGINS:
        return True
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https"):
        return False
    if parts.hostname in _LOCAL_HOSTS:
        return True
    return host is not None and parts.netloc.lower() == host.lower()


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
        # Listening on an address reachable from other computers; see origin_allowed().
        self._network = False
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
        self._network = not is_loopback(host)
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
        host = request.headers.get("Host") if self._network else None
        if not origin_allowed(origin, host):
            log.warning("Rejected WebSocket connection from origin %s", origin)
            return web.Response(status=403, text="Origin is not allowed")
        # No compression: aiohttp 3.14.2+ closes the connection with a protocol
        # error (1002) when the client's first data frame is compressed and a pong
        # came before it, so a page idle for a heartbeat would lose its first request.
        socket = web.WebSocketResponse(
            heartbeat=WEBSOCKET_HEARTBEAT,
            max_msg_size=WEBSOCKET_MAX_MESSAGE_SIZE,
            compress=False,
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

    The core is started, takes the stored routing rules, the stored inbounds
    listen and the stored servers are registered before the application is
    ready. If the core cannot start or take the rules, the application does not
    start; an inbound that cannot listen keeps its error.
    With auto_connect on, the best stored server is connected then if nothing is
    (handlers/auto_connect.py).
    """
    with SettingsStore(DATA_DIR) as settings:
        core_client = MihomoClient()
        scheduler = Scheduler()
        websocket = WebSocketServer()
        sync = ModelSync(websocket)
        sync.register(ModelChannel("server_settings", lambda: [settings.server_settings.get()]))
        sync.register(ModelChannel("subscription_link", settings.subscription_link.get_all))
        sync.register(ModelChannel("reg_filter", settings.reg_filter.get_all))
        sync.register(ModelChannel("outbound_test", settings.outbound_test.get_all))
        sync.register(ModelChannel("outbound_server", settings.outbound_server.get_all))
        sync.register(ModelChannel("inbound_server", settings.inbound_server.get_all))
        sync.register(ModelChannel("routing_rule", settings.routing_rule.get_all))
        tasks = TaskRegistry(on_change=partial(sync.notify, "task"))
        sync.register(ModelChannel("task", tasks.states))
        context = ApplicationContext(
            settings, core_client, scheduler, websocket, sync, AutoConnectState(), tasks=tasks
        )
        init_task = None
        try:
            scheduler.start()
            # The core's test endpoint takes a free port, but not a port of a stored inbound.
            await core_client.service_start(
                {
                    inbound.proxy_port
                    for inbound in settings.inbound_server.get_all()
                    if inbound.proxy_port is not None
                }
            )
            # Before the inbounds, so their traffic follows the rules from the start.
            await apply_routing_rules(context)
            await start_inbound_servers(context)
            await register_outbound_servers(context)
            await on_servers_changed(context)
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
    # Quick checks of the connected server while auto_connect is on.
    context.scheduler.add_job(
        partial(watch_connected_server, context),
        IntervalTrigger(seconds=RETRY_INTERVAL),
        id="watch_connected_server",
    )
    websocket = context.websocket
    websocket.register("add", "subscription_link", partial(add_subscription_link, context))
    websocket.register("delete", "subscription_link", partial(delete_subscription_link, context))
    websocket.register("add", "reg_filter", partial(add_reg_filter, context))
    websocket.register("delete", "reg_filter", partial(delete_reg_filter, context))
    websocket.register("add", "outbound_test", partial(add_outbound_test, context))
    websocket.register("delete", "outbound_test", partial(delete_outbound_test, context))
    websocket.register("add", "inbound_server", partial(add_inbound_server, context))
    websocket.register("change", "inbound_server", partial(change_inbound_server, context))
    websocket.register("delete", "inbound_server", partial(delete_inbound_server, context))
    websocket.register("add", "routing_rule", partial(add_routing_rule, context))
    websocket.register("change", "routing_rule", partial(change_routing_rule, context))
    websocket.register("delete", "routing_rule", partial(delete_routing_rule, context))
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


def _wait_closed(descriptor: int) -> None:
    """Block until the other end of the pipe is closed; what it writes is ignored."""
    try:
        # os.read, not sys.stdin: a thread blocked in a buffered read breaks the exit of Python.
        while os.read(descriptor, 4096):
            pass
    except OSError:
        pass


async def main(*, stop_on_stdin_close: bool = False) -> None:
    """Run the application until a signal or, with stop_on_stdin_close, the end of stdin."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(signum, frame) -> None:
        loop.call_soon_threadsafe(stop.set)

    def watch_stdin(descriptor: int) -> None:
        _wait_closed(descriptor)
        log.info("Standard input closed, stopping")
        try:
            loop.call_soon_threadsafe(stop.set)
        except RuntimeError:
            pass  # The loop is closed: the application has already stopped.

    if stop_on_stdin_close:
        # A daemon thread: a pipe is not awaitable on Windows, and the thread must
        # not keep the process when the application stops for another reason.
        threading.Thread(
            target=watch_stdin, args=(sys.stdin.fileno(),), name="stdin-watch", daemon=True
        ).start()

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
    try:
        WEBSOCKET_HOST, WEBSOCKET_PORT, DATA_DIR = read_environment(os.environ)
    except ValueError as error:
        sys.exit(str(error))
    asyncio.run(main(stop_on_stdin_close=stops_with_stdin(os.environ)))
