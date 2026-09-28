import type { Connection } from '../api/connection.svelte';
import type { OutboundTest } from '../api/protocol';
import { Collection } from './collection.svelte';

/** Server-wide settings: the refresh interval and the tests servers are checked with. */
export class ServerSettingsStore {
  #connection: Connection;
  #collection = new Collection<'server_settings'>();
  /** The single settings object; null until the first snapshot. */
  current = $derived(this.#collection.get(0) ?? null);

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('server_settings', (message) => this.#collection.apply(message));
  }

  /** Restarts the timer: the next automatic refresh is `seconds` from now. */
  setRefreshInterval(seconds: number) {
    return this.#connection.request('change/server_settings', {
      id: 0,
      subscription_refresh_interval: seconds,
    });
  }

  /** Replaces the whole list of tests. */
  setOutboundTests(tests: OutboundTest[]) {
    return this.#connection.request('change/server_settings', { id: 0, outbound_tests: tests });
  }
}
