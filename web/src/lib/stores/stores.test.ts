import { describe, expect, it } from 'vitest';
import { Connection } from '../api/connection.svelte';
import type { ModelName } from '../api/protocol';
import { applyMessage } from './collection.svelte';
import { OutboundServersStore } from './outboundServers.svelte';
import { RegFiltersStore } from './regFilters.svelte';
import { ServerSettingsStore } from './serverSettings.svelte';
import { linkColors, linkLabels, SubscriptionLinksStore } from './subscriptionLinks.svelte';
import { TasksStore } from './tasks.svelte';

describe('applyMessage', () => {
  const a = { id: 'a', v: 1 };
  const b = { id: 'b', v: 1 };

  it('replaces everything on a snapshot', () => {
    const items = new Map([['a', a]]);
    const next = applyMessage(items, { refresh: true, payload: [b], deleted_ids: [] });
    expect([...next.keys()]).toEqual(['b']);
    expect(items.has('a')).toBe(true);
  });

  it('adds, replaces and deletes on changes, keeping unchanged objects', () => {
    const items = new Map([
      ['a', a],
      ['b', b],
    ]);
    const changed = { id: 'b', v: 2 };
    const next = applyMessage(items, {
      refresh: false,
      payload: [changed, { id: 'c', v: 1 }],
      deleted_ids: ['a'],
    });
    expect([...next.keys()]).toEqual(['b', 'c']);
    expect(next.get('b')).toBe(changed);
  });
});

describe('linkLabels', () => {
  it('uses site names and numbers repeated ones', () => {
    const labels = linkLabels([
      { id: '1', url_short: 'https://sub.alpha.com' },
      { id: '2', url_short: 'https://beta.cc' },
      { id: '3', url_short: 'http://alpha.org' },
    ]);
    expect([...labels.values()]).toEqual(['alpha (1)', 'beta', 'alpha (2)']);
  });
});

describe('linkColors', () => {
  it('colors links in order and repeats colors after the last one', () => {
    const links = ['a', 'b', 'c'].map((id) => ({ id, url_short: `https://${id}.example` }));
    expect([...linkColors(links, 2).values()]).toEqual([1, 2, 1]);
  });
});

/** A connection whose subscription messages are delivered by hand. */
function fakeConnection() {
  const connection = new Connection('ws://unused');
  const listeners = new Map<string, (message: unknown) => void>();
  connection.on = ((model: ModelName, listener: (message: unknown) => void) => {
    listeners.set(model, listener);
    return () => listeners.delete(model);
  }) as Connection['on'];
  const deliver = (
    model: ModelName,
    payload: unknown[],
    refresh = true,
    deleted_ids: string[] = [],
  ) => listeners.get(model)?.({ type: 'subscription', model, refresh, payload, deleted_ids });
  return { connection, deliver };
}

describe('stores', () => {
  it('derive the connected server and counts per subscription', () => {
    const { connection, deliver } = fakeConnection();
    const servers = new OutboundServersStore(connection);
    deliver('outbound_server', [
      { id: 's1', subscription_id: 'x', protocol: 'vless', is_connected: false },
      { id: 's2', subscription_id: 'x', protocol: 'hysteria', is_connected: true },
      { id: 's3', subscription_id: null, protocol: 'vless', is_connected: false },
    ]);
    expect(servers.connected?.id).toBe('s2');
    expect(servers.countBySubscription.get('x')).toBe(2);
    expect(servers.protocols).toEqual(['hysteria', 'vless']);
    deliver('outbound_server', [], false, ['s2']);
    expect(servers.connected).toBeNull();
  });

  it('notice when the server drops the connected server', () => {
    const { connection, deliver } = fakeConnection();
    const servers = new OutboundServersStore(connection);
    deliver('outbound_server', [{ id: 's1', is_connected: false }]);
    expect(servers.lost).toBe(false);
    deliver('outbound_server', [{ id: 's1', is_connected: true }], false);
    deliver('outbound_server', [{ id: 's1', is_connected: false }], false);
    expect(servers.lost).toBe(true);
    deliver('outbound_server', [{ id: 's2', is_connected: true }], false);
    expect(servers.lost).toBe(false);
    deliver('outbound_server', [], false, ['s2']);
    expect(servers.lost).toBe(true);
  });

  it('count servers filtered by name', () => {
    const { connection, deliver } = fakeConnection();
    const servers = new OutboundServersStore(connection);
    deliver('outbound_server', [
      { id: 's1', filtered: 'by_reg_filter', is_connected: false },
      { id: 's2', filtered: 'by_ping', is_connected: false },
      { id: 's3', filtered: null, is_connected: false },
    ]);
    expect(servers.filteredByName).toBe(1);
    deliver(
      'outbound_server',
      [{ id: 's2', filtered: 'by_reg_filter', is_connected: false }],
      false,
    );
    expect(servers.filteredByName).toBe(2);
  });

  it('keep name filters and send their requests', () => {
    const { connection, deliver } = fakeConnection();
    const sent: unknown[] = [];
    connection.request = ((key: string, payload: unknown) => {
      sent.push([key, payload]);
      return Promise.resolve({});
    }) as Connection['request'];
    const filters = new RegFiltersStore(connection);
    deliver('reg_filter', [
      { id: 'f1', reg: '^RU' },
      { id: 'f2', reg: '(?i)russia' },
    ]);
    deliver('reg_filter', [], false, ['f1']);
    expect(filters.list).toEqual([{ id: 'f2', reg: '(?i)russia' }]);
    void filters.add(' US$');
    void filters.remove('f2');
    expect(sent).toEqual([
      ['add/reg_filter', { reg: ' US$' }],
      ['delete/reg_filter', { id: 'f2' }],
    ]);
  });

  it('follow auto-connect and send its changes', () => {
    const { connection, deliver } = fakeConnection();
    const sent: unknown[] = [];
    connection.request = ((key: string, payload: unknown) => {
      sent.push([key, payload]);
      return Promise.resolve({});
    }) as Connection['request'];
    const settings = new ServerSettingsStore(connection);
    deliver('server_settings', [{ id: 0, auto_connect: false }]);
    expect(settings.current?.auto_connect).toBe(false);
    void settings.setAutoConnect(true);
    expect(sent).toEqual([['change/server_settings', { id: 0, auto_connect: true }]]);
    deliver('server_settings', [{ id: 0, auto_connect: true }], false);
    expect(settings.current?.auto_connect).toBe(true);
  });

  it('follow task status', () => {
    const { connection, deliver } = fakeConnection();
    const tasks = new TasksStore(connection);
    deliver('task', [
      { id: 'refresh_subscriptions', status: 'stopped' },
      { id: 'test_outbound_servers', status: 'running' },
    ]);
    expect(tasks.refreshing).toBe(false);
    expect(tasks.testing).toBe(true);
    deliver('task', [{ id: 'test_outbound_servers', status: 'stopped' }], false);
    expect(tasks.testing).toBe(false);
  });

  it('label missing subscriptions', () => {
    const { connection, deliver } = fakeConnection();
    const links = new SubscriptionLinksStore(connection);
    deliver('subscription_link', [{ id: '1', url_short: 'https://sub.provider.com' }]);
    expect(links.label('1')).toBe('provider');
    expect(links.label('gone')).toBe('Removed subscription');
    expect(links.label(null)).toBe('No subscription');
  });
});
