import type { Connection } from '../api/connection.svelte';
import type { RoutingAction } from '../api/protocol';
import { Collection } from './collection.svelte';

/**
 * Where the inbounds' traffic goes; the first matching rule wins. The server
 * renumbers the other rules itself when one is added, moved or deleted.
 */
export class RoutingRulesStore {
  #connection: Connection;
  #collection = new Collection<'routing_rule'>();
  /** In the order they are checked. */
  list = $derived([...this.#collection.list].sort((a, b) => a.priority - b.priority));

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('routing_rule', (message) => this.#collection.apply(message));
  }

  /** The new rule is checked last. */
  add(reg: string, action: RoutingAction) {
    return this.#connection.request('add/routing_rule', { reg, action });
  }

  /** Puts the rule at the priority; the rules in between shift towards its old place. */
  move(id: string, priority: number) {
    return this.#connection.request('change/routing_rule', { id, priority });
  }

  remove(id: string) {
    return this.#connection.request('delete/routing_rule', { id });
  }
}
