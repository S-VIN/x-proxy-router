import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Connection, RETRY_DELAYS_MS } from './connection.svelte';
import { RequestError } from './errors';
import { MODEL_NAMES, type ModelName } from './protocol';

class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sent: Record<string, unknown>[] = [];
  closed = false;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }

  send(frame: string) {
    this.sent.push(JSON.parse(frame));
  }

  close() {
    this.closed = true;
  }

  open() {
    this.onopen?.(new Event('open'));
  }

  receive(message: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(message) }));
  }

  drop() {
    this.onclose?.(new CloseEvent('close'));
  }

  snapshots() {
    for (const model of MODEL_NAMES) this.receive(snapshot(model, []));
  }
}

function snapshot(model: ModelName, payload: unknown[]) {
  return { type: 'subscription', model, refresh: true, payload, deleted_ids: [] };
}

function connect() {
  const connection = new Connection(
    'ws://test/ws',
    (url) => new FakeSocket(url) as unknown as WebSocket,
  );
  connection.start();
  const socket = FakeSocket.all.at(-1)!;
  return { connection, socket };
}

beforeEach(() => {
  FakeSocket.all = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Connection', () => {
  it('is ready only after snapshots of every model', () => {
    const { connection, socket } = connect();
    expect(connection.status).toBe('connecting');
    socket.open();
    expect(connection.status).toBe('online');
    expect(connection.ready).toBe(false);
    for (const model of MODEL_NAMES.slice(0, -1)) socket.receive(snapshot(model, []));
    expect(connection.ready).toBe(false);
    socket.receive(snapshot('task', []));
    expect(connection.ready).toBe(true);
  });

  it('routes subscription messages to listeners of their model', () => {
    const { connection, socket } = connect();
    const tasks = vi.fn();
    const links = vi.fn();
    connection.on('task', tasks);
    const off = connection.on('subscription_link', links);
    socket.open();
    const message = snapshot('task', [{ id: 'refresh_subscriptions', status: 'stopped' }]);
    socket.receive(message);
    expect(tasks).toHaveBeenCalledWith(message);
    expect(links).not.toHaveBeenCalled();
    off();
    socket.receive(snapshot('subscription_link', []));
    expect(links).not.toHaveBeenCalled();
  });

  it('matches responses to requests by request_id', async () => {
    const { connection, socket } = connect();
    socket.open();
    socket.snapshots();
    const first = connection.request('add/subscription_link', { url: 'https://a.example/sub' });
    const second = connection.request('request/refresh_subscriptions', {});
    expect(socket.sent).toEqual([
      {
        type: 'add',
        model: 'subscription_link',
        request_id: '1',
        payload: { url: 'https://a.example/sub' },
      },
      { type: 'request', model: 'refresh_subscriptions', request_id: '2', payload: {} },
    ]);
    socket.receive({
      type: 'response',
      model: 'refresh_subscriptions',
      request_id: '2',
      ok: false,
      payload: {},
      error: { code: 'subscription_error', message: 'failed', details: { failed_id: 'x' } },
    });
    socket.receive({
      type: 'response',
      model: 'subscription_link',
      request_id: '1',
      ok: true,
      payload: { id: 'new' },
    });
    await expect(first).resolves.toEqual({ id: 'new' });
    const error = await second.catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(RequestError);
    expect(error).toMatchObject({ code: 'subscription_error', details: { failed_id: 'x' } });
  });

  it('rejects requests while offline and when the socket closes', async () => {
    const { connection, socket } = connect();
    await expect(connection.request('request/test_outbound_servers', {})).rejects.toMatchObject({
      code: 'disconnected',
    });
    socket.open();
    const pending = connection.request('request/test_outbound_servers', {});
    socket.drop();
    await expect(pending).rejects.toMatchObject({ code: 'disconnected' });
    expect(connection.status).toBe('offline');
  });

  it('reconnects with growing pauses and starts over after a snapshot', () => {
    const { connection, socket } = connect();
    socket.drop();
    expect(connection.status).toBe('offline');
    vi.advanceTimersByTime(RETRY_DELAYS_MS[0]);
    expect(FakeSocket.all).toHaveLength(2);
    FakeSocket.all[1]!.drop();
    vi.advanceTimersByTime(RETRY_DELAYS_MS[0]);
    expect(FakeSocket.all).toHaveLength(2);
    vi.advanceTimersByTime(RETRY_DELAYS_MS[1] - RETRY_DELAYS_MS[0]);
    expect(FakeSocket.all).toHaveLength(3);

    const third = FakeSocket.all[2]!;
    third.open();
    third.snapshots();
    expect(connection.ready).toBe(true);
    third.drop();
    expect(connection.ready).toBe(false);
    vi.advanceTimersByTime(RETRY_DELAYS_MS[0]);
    expect(FakeSocket.all).toHaveLength(4);
  });

  it('reconnects at once on request and stops for good', () => {
    const { connection, socket } = connect();
    socket.drop();
    connection.reconnectNow();
    expect(FakeSocket.all).toHaveLength(2);
    connection.stop();
    expect(FakeSocket.all[1]!.closed).toBe(true);
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(2);
  });
});
