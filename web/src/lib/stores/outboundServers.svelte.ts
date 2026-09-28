import type { Connection } from '../api/connection.svelte';
import { Collection } from './collection.svelte';

/** Servers loaded from subscriptions, with their check results. */
export class OutboundServersStore {
  #connection: Connection;
  #collection = new Collection<'outbound_server'>();
  list = $derived(this.#collection.list);
  /** The server main traffic goes through, if any. */
  connected = $derived(this.list.find((server) => server.is_connected) ?? null);
  /** Number of servers per subscription id. */
  countBySubscription = $derived.by(() => {
    const counts = new Map<string | null, number>();
    for (const server of this.list) {
      counts.set(server.subscription_id, (counts.get(server.subscription_id) ?? 0) + 1);
    }
    return counts;
  });
  protocols = $derived([...new Set(this.list.map((server) => server.protocol))].sort());
  /** Servers whose names match a filter; that reason wins, so each matching server counts. */
  filteredByName = $derived(
    this.list.filter((server) => server.filtered === 'by_reg_filter').length,
  );
  /**
   * The server dropped the connection while the page was open: the connected server
   * was removed or can no longer be used. Connecting never leaves no server connected,
   * so losing the connected server is always this. Cleared by the next connection.
   */
  lost = $state(false);

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('outbound_server', (message) => {
      const before = this.connected;
      this.#collection.apply(message);
      if (this.connected) this.lost = false;
      else if (before) this.lost = true;
    });
  }

  get(id: string) {
    return this.#collection.get(id);
  }

  /** Route main traffic through the server; there is no disconnect. */
  connect(id: string) {
    return this.#connection.request('request/connect_outbound_server', { id });
  }
}
