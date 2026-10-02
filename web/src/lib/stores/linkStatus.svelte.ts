import type { Connection } from '../api/connection.svelte';
import { linkDescription, linkState } from '../linkState';
import type { OutboundServersStore } from './outboundServers.svelte';

/** The connection state shown by the logo and the favicon; derived, sends nothing. */
export class LinkStatusStore {
  #connection: Connection;
  #servers: OutboundServersStore;

  state = $derived.by(() =>
    linkState(this.#connection.status, this.#servers.connected, this.#servers.lost),
  );

  /** Why the state is what it is, for tooltips and screen readers. */
  description = $derived.by(() =>
    linkDescription(this.#connection.status, this.#servers.connected, this.#servers.lost),
  );

  constructor(connection: Connection, servers: OutboundServersStore) {
    this.#connection = connection;
    this.#servers = servers;
  }
}
