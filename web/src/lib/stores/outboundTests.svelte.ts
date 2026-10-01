import type { Connection } from '../api/connection.svelte';
import type { TestRule } from '../api/protocol';
import { siteLabels } from '../format';
import { Collection } from './collection.svelte';

/** Tests servers are checked with; added and deleted, never changed. */
export class OutboundTestsStore {
  #connection: Connection;
  #collection = new Collection<'outbound_test'>();
  /** In server order; new tests come last. */
  list = $derived(this.#collection.list);
  /** Tests have no names: each is named after the site of its URL. */
  labels = $derived(siteLabels(this.list, (test) => test.url));

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('outbound_test', (message) => this.#collection.apply(message));
  }

  label(id: string): string {
    return this.labels.get(id) ?? 'Removed test';
  }

  /** Servers run the test from their next check on. */
  add(url: string, rule: TestRule) {
    return this.#connection.request('add/outbound_test', { url, rule });
  }

  /** Servers keep its result until their next check; it is not shown. */
  remove(id: string) {
    return this.#connection.request('delete/outbound_test', { id });
  }
}
