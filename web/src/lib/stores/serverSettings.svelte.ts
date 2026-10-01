import type { Connection } from '../api/connection.svelte';
import { Collection } from './collection.svelte';

/** Server-wide settings: the refresh interval and auto-connect. */
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

  /**
   * Turning auto-connect on resolves after the server has chosen a server, which
   * takes a few seconds: candidates are checked before connecting.
   */
  setAutoConnect(enabled: boolean) {
    return this.#connection.request('change/server_settings', { id: 0, auto_connect: enabled });
  }
}
