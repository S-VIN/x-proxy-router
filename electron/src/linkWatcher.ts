import type { OutboundServer, SubscriptionMessage } from '../../web/src/lib/api/protocol';
import type { ConnectionStatus } from '../../web/src/lib/api/status';
import { type LinkState, linkDescription, linkState } from '../../web/src/lib/linkState';

/** Pauses before reconnecting after consecutive failures; the last one repeats. */
const RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000, 10000] as const;

export interface Link {
  state: LinkState;
  /** Why the state is what it is, for the tooltip. */
  description: string;
}

type ConnectedServer = Pick<OutboundServer, 'id' | 'name' | 'rating'>;

/**
 * The state of the proxy connection from the messages of server/PROTOCOL.md,
 * the same one the web interface shows with its logo: only the connected
 * server matters, so only it is remembered.
 */
export class LinkTracker {
  status: ConnectionStatus = 'connecting';
  #connected: ConnectedServer | null = null;
  /** The connected server was removed or can no longer be used; cleared by the next one. */
  #lost = false;

  get link(): Link {
    return {
      state: linkState(this.status, this.#connected, this.#lost),
      description: linkDescription(this.status, this.#connected, this.#lost),
    };
  }

  /** Take one text frame of the server; frames of other models change nothing. */
  receive(frame: string): void {
    let message: unknown;
    try {
      message = JSON.parse(frame);
    } catch {
      return;
    }
    if (!isOutboundServers(message)) return;
    const before = this.#connected;
    let connected = message.refresh ? null : before;
    if (connected && message.deleted_ids.includes(connected.id)) connected = null;
    for (const server of message.payload) {
      if (server.is_connected) {
        connected = { id: server.id, name: server.name, rating: server.rating };
      } else if (connected?.id === server.id) {
        connected = null;
      }
    }
    this.#connected = connected;
    if (connected) this.#lost = false;
    else if (before) this.#lost = true;
  }
}

function isOutboundServers(message: unknown): message is SubscriptionMessage<'outbound_server'> {
  if (typeof message !== 'object' || message === null) return false;
  const { type, model, payload, deleted_ids } = message as Record<string, unknown>;
  return (
    type === 'subscription' &&
    model === 'outbound_server' &&
    Array.isArray(payload) &&
    Array.isArray(deleted_ids)
  );
}

/**
 * Follows the server over its own WebSocket, so the tray icon is right while
 * the window is closed. The main process sends no Origin, which the server accepts.
 */
export class LinkWatcher {
  #url: string;
  #onChange: (link: Link) => void;
  #tracker = new LinkTracker();
  #socket: WebSocket | null = null;
  #failures = 0;
  #retryTimer: ReturnType<typeof setTimeout> | undefined;
  #running = false;
  #last = '';

  constructor(url: string, onChange: (link: Link) => void) {
    this.#url = url;
    this.#onChange = onChange;
  }

  get link(): Link {
    return this.#tracker.link;
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    this.#open();
  }

  /** Stop following; the state becomes "no connection to the server". */
  stop(): void {
    this.#running = false;
    clearTimeout(this.#retryTimer);
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
    this.#setStatus('offline');
  }

  #open(): void {
    this.#setStatus(this.#failures === 0 ? 'connecting' : 'offline');
    const socket = new WebSocket(this.#url);
    this.#socket = socket;
    socket.addEventListener('open', () => {
      if (this.#socket !== socket) return;
      this.#failures = 0;
      this.#setStatus('online');
    });
    socket.addEventListener('message', (event) => {
      if (this.#socket !== socket || typeof event.data !== 'string') return;
      this.#tracker.receive(event.data);
      this.#notify();
    });
    // An error is always followed by close.
    socket.addEventListener('close', () => {
      if (this.#socket !== socket) return;
      this.#socket = null;
      this.#setStatus('offline');
      if (!this.#running) return;
      const delay = RETRY_DELAYS_MS[Math.min(this.#failures, RETRY_DELAYS_MS.length - 1)];
      this.#failures += 1;
      this.#retryTimer = setTimeout(() => this.#open(), delay);
    });
  }

  #setStatus(status: ConnectionStatus): void {
    this.#tracker.status = status;
    this.#notify();
  }

  #notify(): void {
    const link = this.#tracker.link;
    const key = `${link.state}\n${link.description}`;
    if (key === this.#last) return;
    this.#last = key;
    this.#onChange(link);
  }
}
