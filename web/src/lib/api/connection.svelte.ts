import { RequestError } from './errors';
import {
  MODEL_NAMES,
  type ModelName,
  type RequestKey,
  type RequestPayload,
  type RequestResult,
  type ServerMessage,
  type SubscriptionMessage,
} from './protocol';
import type { ConnectionStatus } from './status';

export type { ConnectionStatus };

export type SocketFactory = (url: string) => WebSocket;

type Listener<M extends ModelName> = (message: SubscriptionMessage<M>) => void;

interface PendingRequest {
  resolve: (payload: Record<string, unknown>) => void;
  reject: (error: RequestError) => void;
}

/** Pauses before reconnecting after consecutive failures; the last one repeats. */
export const RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000, 10000] as const;

/**
 * The single WebSocket to the server. It routes subscription messages to the
 * listeners of each model, matches responses to requests by request_id and
 * reconnects with a growing pause. Stores use it; components never do.
 */
export class Connection {
  /** connecting: opening a socket; online: open; offline: waiting to retry. */
  status = $state<ConnectionStatus>('connecting');
  /** When the next attempt starts, while offline. */
  retryAt = $state<number | null>(null);
  /** Snapshots of all models arrived on the current socket, so the data is current. */
  synced = $state(false);
  /** Data is current and requests can be sent. */
  ready = $derived(this.status === 'online' && this.synced);

  #url: string;
  #createSocket: SocketFactory;
  #socket: WebSocket | null = null;
  #listeners = new Map<ModelName, Set<Listener<ModelName>>>();
  #pending = new Map<string, PendingRequest>();
  #nextRequestId = 1;
  #failures = 0;
  #retryTimer: ReturnType<typeof setTimeout> | undefined;
  #missingSnapshots = new Set<ModelName>();
  #running = false;

  constructor(url: string, createSocket: SocketFactory = (url) => new WebSocket(url)) {
    this.#url = url;
    this.#createSocket = createSocket;
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    this.#open();
  }

  stop(): void {
    this.#running = false;
    clearTimeout(this.#retryTimer);
    const socket = this.#socket;
    this.#closed();
    socket?.close();
    this.status = 'offline';
    this.retryAt = null;
  }

  /** Skip the pause before the next attempt. */
  reconnectNow(): void {
    if (!this.#running || this.status !== 'offline') return;
    clearTimeout(this.#retryTimer);
    this.#open();
  }

  /** Receive snapshots and changes of a model. Returns a function that unsubscribes. */
  on<M extends ModelName>(model: M, listener: Listener<M>): () => void {
    let listeners = this.#listeners.get(model);
    if (!listeners) {
      listeners = new Set();
      this.#listeners.set(model, listeners);
    }
    const stored = listener as unknown as Listener<ModelName>;
    listeners.add(stored);
    return () => listeners.delete(stored);
  }

  /**
   * Send a request; resolves with the response payload or rejects with RequestError.
   * Changes caused by the request arrive in subscriptions before it resolves.
   * There is no timeout: refreshing subscriptions or checking servers takes minutes.
   */
  request<K extends RequestKey>(key: K, payload: RequestPayload<K>): Promise<RequestResult<K>> {
    const socket = this.#socket;
    if (this.status !== 'online' || socket === null) {
      return Promise.reject(new RequestError('disconnected', 'Not connected to the server'));
    }
    const [type, model] = key.split('/');
    const request_id = String(this.#nextRequestId++);
    return new Promise((resolve, reject) => {
      this.#pending.set(request_id, {
        resolve: (result) => resolve(result as RequestResult<K>),
        reject,
      });
      socket.send(JSON.stringify({ type, model, request_id, payload }));
    });
  }

  #open(): void {
    this.status = 'connecting';
    this.retryAt = null;
    this.synced = false;
    this.#missingSnapshots = new Set(MODEL_NAMES);
    let socket: WebSocket;
    try {
      socket = this.#createSocket(this.#url);
    } catch (error) {
      console.error('Cannot open WebSocket', error);
      this.#retryLater();
      return;
    }
    this.#socket = socket;
    socket.onopen = () => {
      if (socket === this.#socket) this.status = 'online';
    };
    socket.onmessage = (event: MessageEvent) => {
      if (socket === this.#socket) this.#receive(event.data);
    };
    socket.onclose = () => {
      if (socket !== this.#socket) return;
      this.#closed();
      if (this.#running) this.#retryLater();
    };
  }

  /** Forget the socket; requests waiting for a response fail. */
  #closed(): void {
    this.#socket = null;
    this.synced = false;
    const pending = [...this.#pending.values()];
    this.#pending.clear();
    for (const request of pending) {
      request.reject(new RequestError('disconnected', 'Connection closed before the response'));
    }
  }

  #retryLater(): void {
    const index = Math.min(this.#failures, RETRY_DELAYS_MS.length - 1);
    const delay = RETRY_DELAYS_MS[index] ?? RETRY_DELAYS_MS[0];
    this.#failures += 1;
    this.status = 'offline';
    this.retryAt = Date.now() + delay;
    this.#retryTimer = setTimeout(() => this.#open(), delay);
  }

  #receive(data: unknown): void {
    let message: ServerMessage;
    try {
      message = JSON.parse(String(data));
    } catch {
      console.error('Unreadable message from the server', data);
      return;
    }
    if (message.type === 'subscription') {
      for (const listener of this.#listeners.get(message.model) ?? []) listener(message);
      if (message.refresh && this.#missingSnapshots.delete(message.model)) {
        if (this.#missingSnapshots.size === 0) {
          this.synced = true;
          this.#failures = 0;
        }
      }
    } else if (message.type === 'response') {
      this.#resolve(message);
    }
  }

  #resolve(message: Extract<ServerMessage, { type: 'response' }>): void {
    const pending = message.request_id === null ? undefined : this.#pending.get(message.request_id);
    if (!pending || message.request_id === null) {
      console.warn('Response to an unknown request', message);
      return;
    }
    this.#pending.delete(message.request_id);
    if (message.ok) {
      pending.resolve(message.payload);
    } else {
      pending.reject(
        RequestError.fromResponse(
          message.error ?? { code: 'internal_error', message: 'No error in response', details: {} },
        ),
      );
    }
  }
}

/** The WebSocket next to the page (the server serves both), unless VITE_WS_URL is set. */
export function serverUrl(): string {
  const configured = import.meta.env.VITE_WS_URL;
  if (configured) return configured;
  const url = new URL('/ws', window.location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.href;
}
