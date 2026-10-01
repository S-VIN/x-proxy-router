import type { Connection } from '../api/connection.svelte';
import type { InboundServer, InboundSettings } from '../api/protocol';
import { Collection } from './collection.svelte';

/** Ports where the core accepts traffic of apps; it goes by the routing rules. */
export class InboundServersStore {
  #connection: Connection;
  #collection = new Collection<'inbound_server'>();
  /** In server order; new inbounds come last. */
  list = $derived(this.#collection.list);

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('inbound_server', (message) => this.#collection.apply(message));
  }

  get(id: string): InboundServer | undefined {
    return this.#collection.get(id);
  }

  /** An enabled inbound listens before this resolves; if it cannot, nothing is added. */
  add(type: InboundServer['type'], settings: InboundSettings) {
    return this.#connection.request('add/inbound_server', { type, ...settings });
  }

  /**
   * Omitted fields keep their values. The listener restarts with the new values
   * before this resolves, so it also retries an inbound with an error.
   */
  change(id: string, settings: InboundSettings = {}) {
    return this.#connection.request('change/inbound_server', { id, ...settings });
  }

  /** The core stops listening before this resolves. */
  remove(id: string) {
    return this.#connection.request('delete/inbound_server', { id });
  }
}
