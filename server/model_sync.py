"""Keep client copies of model collections in sync over WebSocket.

Every message has the same shape:

    {"type": "subscription", "model": "outbound_server", "refresh": false,
     "payload": [...], "deleted_ids": [...]}

A connecting client receives one message with refresh=true per model: it replaces
the whole collection with payload. Later messages carry only changed objects in
payload and removed ids in deleted_ids; the client applies deletions first.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

from .models.serialization import JsonValue, serialize

if TYPE_CHECKING:
    from .main import WebSocketServer

SUBSCRIPTION = "subscription"


ModelId = str | int


class Identified(Protocol):
    @property
    def id(self) -> ModelId: ...


T = TypeVar("T", bound=Identified)


class ModelChannel(Generic[T]):
    """One model collection, compared with the state last sent to clients.

    Objects are compared as serialized JSON, so secret fields and objects written
    unchanged produce no messages.
    """

    def __init__(self, model: str, load_all: Callable[[], list[T]]):
        if not model:
            raise ValueError("Model name must not be empty")
        self.model = model
        self._load_all = load_all
        self._sent: dict[ModelId, JsonValue] = {}

    def changes(self) -> JsonValue | None:
        """Reload the collection; return the message with differences, or None."""
        current = {item.id: serialize(item) for item in self._load_all()}
        changed = [
            value
            for id_, value in current.items()
            if id_ not in self._sent or self._sent[id_] != value
        ]
        deleted: list[JsonValue] = [id_ for id_ in self._sent if id_ not in current]
        self._sent = current
        if not changed and not deleted:
            return None
        return self._message(changed, deleted, refresh=False)

    def snapshot(self) -> JsonValue:
        """The full collection as last sent to clients."""
        return self._message(list(self._sent.values()), [], refresh=True)

    def _message(
        self, payload: list[JsonValue], deleted_ids: list[JsonValue], *, refresh: bool
    ) -> JsonValue:
        return {
            "type": SUBSCRIPTION,
            "model": self.model,
            "refresh": refresh,
            "payload": payload,
            "deleted_ids": deleted_ids,
        }


class ModelSync:
    """Registry of synchronized models, available to handlers as context.sync.

    Handlers call `await context.sync.notify("model")` after writing that model's
    store. Messages are queued without awaiting in between, so a snapshot and the
    changes after it reach each client in order.
    """

    def __init__(self, websocket: "WebSocketServer"):
        self._websocket = websocket
        self._channels: dict[str, ModelChannel] = {}
        websocket.add_connect_listener(self.send_snapshots)

    def register(self, channel: ModelChannel) -> None:
        if channel.model in self._channels:
            raise ValueError("A channel is already registered for this model")
        self._channels[channel.model] = channel

    async def notify(self, model: str) -> None:
        """Send objects changed since the last message to all clients.

        Unknown models raise KeyError.
        """
        self._broadcast_changes(self._channels[model])

    def send_snapshots(self, connection_id: str) -> None:
        """Send every model's full collection to a newly connected client."""
        for channel in self._channels.values():
            # Snapshots read the store, so writes not yet followed by notify()
            # reach the other clients first; the new one gets them in its snapshot.
            self._broadcast_changes(channel, exclude=connection_id)
            self._websocket.send(connection_id, channel.snapshot())

    def _broadcast_changes(self, channel: ModelChannel, *, exclude: str | None = None) -> None:
        message = channel.changes()
        if message is not None:
            self._websocket.broadcast(message, exclude=exclude)
