import { describe, expect, it } from 'vitest';
import { LinkTracker } from './linkWatcher';

function servers(
  payload: { id: string; name?: string; rating?: number | null; is_connected?: boolean }[],
  options: { refresh?: boolean; deleted?: string[] } = {},
): string {
  return JSON.stringify({
    type: 'subscription',
    model: 'outbound_server',
    refresh: options.refresh ?? false,
    payload: payload.map((server) => ({
      name: server.id,
      rating: null,
      is_connected: false,
      ...server,
    })),
    deleted_ids: options.deleted ?? [],
  });
}

function online(): LinkTracker {
  const tracker = new LinkTracker();
  tracker.status = 'online';
  return tracker;
}

describe('LinkTracker', () => {
  it('knows nothing works until the server answers', () => {
    const tracker = new LinkTracker();
    expect(tracker.link.state).toBe('none');
    tracker.status = 'offline';
    expect(tracker.link).toEqual({
      state: 'failed',
      description: 'No connection to the x-proxy-router server',
    });
  });

  it('follows the connected server of a snapshot and of changes', () => {
    const tracker = online();
    tracker.receive(servers([{ id: 'a' }, { id: 'b', name: 'Berlin', is_connected: true }]));
    expect(tracker.link).toEqual({
      state: 'working',
      description: 'Traffic goes through Berlin',
    });
    // The server switches: the new one and the old one come in one message, in any order.
    tracker.receive(servers([{ id: 'a', name: 'Oslo', is_connected: true }, { id: 'b' }]));
    expect(tracker.link.description).toBe('Traffic goes through Oslo');
    tracker.receive(servers([{ id: 'a' }, { id: 'b', name: 'Berlin', is_connected: true }]));
    expect(tracker.link.description).toBe('Traffic goes through Berlin');
    // Other servers change without touching the connected one.
    tracker.receive(servers([{ id: 'c', rating: 0 }]));
    expect(tracker.link.state).toBe('working');
  });

  it('fails when the connected server failed its check', () => {
    const tracker = online();
    tracker.receive(servers([{ id: 'a', is_connected: true, rating: 70 }]));
    tracker.receive(servers([{ id: 'a', is_connected: true, rating: 0 }]));
    expect(tracker.link).toEqual({ state: 'failed', description: 'a failed its last check' });
  });

  it('fails when the connected server is lost, until another is connected', () => {
    for (const lose of [
      servers([], { deleted: ['a'] }),
      servers([{ id: 'a' }]),
      servers([{ id: 'b' }], { refresh: true }),
    ]) {
      const tracker = online();
      tracker.receive(servers([{ id: 'a', is_connected: true }]));
      tracker.receive(lose);
      expect(tracker.link.state).toBe('failed');
      expect(tracker.link.description).toMatch(/removed or can no longer be used/);
      tracker.receive(servers([{ id: 'b', is_connected: true }]));
      expect(tracker.link.state).toBe('working');
    }
  });

  it('is none when nothing was ever connected', () => {
    const tracker = online();
    tracker.receive(servers([{ id: 'a' }], { refresh: true }));
    tracker.receive(servers([], { deleted: ['a'] }));
    expect(tracker.link).toEqual({ state: 'none', description: 'No server is connected' });
  });

  it('ignores other models, responses and broken frames', () => {
    const tracker = online();
    tracker.receive(servers([{ id: 'a', is_connected: true }]));
    for (const frame of [
      'not json',
      'null',
      '[]',
      JSON.stringify({ type: 'subscription', model: 'task', refresh: true, payload: [] }),
      JSON.stringify({ type: 'response', model: 'outbound_server', ok: true, payload: {} }),
      JSON.stringify({ type: 'subscription', model: 'outbound_server', payload: 'x' }),
    ]) {
      tracker.receive(frame);
      expect(tracker.link.state).toBe('working');
    }
  });
});
