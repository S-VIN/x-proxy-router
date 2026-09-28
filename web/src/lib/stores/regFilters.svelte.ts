import type { Connection } from '../api/connection.svelte';
import { Collection } from './collection.svelte';

/**
 * Filters of servers by name. The server matches names itself: a matching server
 * comes with filtered = by_reg_filter, so the client never runs the expressions.
 */
export class RegFiltersStore {
  #connection: Connection;
  #collection = new Collection<'reg_filter'>();
  /** In server order; new filters come last. */
  list = $derived(this.#collection.list);

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('reg_filter', (message) => this.#collection.apply(message));
  }

  /** Servers whose names match are filtered before this resolves. */
  add(reg: string) {
    return this.#connection.request('add/reg_filter', { reg });
  }

  /** Servers no other filter matches are unfiltered before this resolves. */
  remove(id: string) {
    return this.#connection.request('delete/reg_filter', { id });
  }
}
