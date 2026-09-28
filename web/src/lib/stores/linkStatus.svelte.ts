import type { Connection, ConnectionStatus } from '../api/connection.svelte';
import type { OutboundServer } from '../api/protocol';
import type { OutboundServersStore } from './outboundServers.svelte';

/**
 * State of the proxy connection:
 * - none: no server is connected;
 * - working: traffic goes through a server;
 * - failed: an error, and there is no working connection.
 */
export type LinkState = 'none' | 'working' | 'failed';

export function linkState(
  status: ConnectionStatus,
  server: Pick<OutboundServer, 'rating'> | null,
  lost: boolean,
): LinkState {
  // Without the x-proxy-router server nothing can be known to work.
  if (status === 'offline') return 'failed';
  // Rating 0: the last check found the server unavailable or failing every test.
  // An unchecked server counts as working: the core switched to it.
  if (server) return server.rating === 0 ? 'failed' : 'working';
  return lost ? 'failed' : 'none';
}

/** The connection state shown by the logo and the favicon; derived, sends nothing. */
export class LinkStatusStore {
  #connection: Connection;
  #servers: OutboundServersStore;

  state = $derived.by(() =>
    linkState(this.#connection.status, this.#servers.connected, this.#servers.lost),
  );

  /** Why the state is what it is, for tooltips and screen readers. */
  description = $derived.by(() => {
    const server = this.#servers.connected;
    if (this.#connection.status === 'offline') return 'No connection to the x-proxy-router server';
    if (server && server.rating === 0) return `${server.name} failed its last check`;
    if (server) return `Traffic goes through ${server.name}`;
    if (this.#servers.lost) return 'The connected server was removed or can no longer be used';
    return 'No server is connected';
  });

  constructor(connection: Connection, servers: OutboundServersStore) {
    this.#connection = connection;
    this.#servers = servers;
  }
}
