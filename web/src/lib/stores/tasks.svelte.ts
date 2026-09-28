import type { Connection } from '../api/connection.svelte';
import type { TaskId } from '../api/protocol';
import { Collection } from './collection.svelte';

/**
 * Long server tasks. Progress indicators follow the task status, not pending
 * requests, so scheduled runs show up too.
 */
export class TasksStore {
  #connection: Connection;
  #collection = new Collection<'task'>();
  refreshing = $derived(this.isRunning('refresh_subscriptions'));
  testing = $derived(this.isRunning('test_outbound_servers'));

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('task', (message) => this.#collection.apply(message));
  }

  isRunning(id: TaskId): boolean {
    return this.#collection.get(id)?.status === 'running';
  }

  /** Resolves when the refresh (this one or one already running) ends. */
  refreshSubscriptions() {
    return this.#connection.request('request/refresh_subscriptions', {});
  }

  /** Resolves when all servers are checked. Rejected with conflict while refreshing. */
  testServers() {
    return this.#connection.request('request/test_outbound_servers', {});
  }
}
