import type { ModelName, Models, SubscriptionMessage } from '../api/protocol';

type Id = string | number;

/** Apply a subscription message to an id → object map; returns a new map. */
export function applyMessage<T extends { id: Id }>(
  items: ReadonlyMap<T['id'], T>,
  message: { refresh: boolean; payload: T[]; deleted_ids: T['id'][] },
): Map<T['id'], T> {
  const next = message.refresh ? new Map<T['id'], T>() : new Map(items);
  for (const id of message.deleted_ids) next.delete(id);
  for (const item of message.payload) next.set(item.id, item);
  return next;
}

/**
 * The client copy of one model. Objects are replaced whole, never mutated, so
 * unchanged objects keep their identity and their rows are not redrawn.
 */
export class Collection<M extends ModelName> {
  items = $state.raw<ReadonlyMap<Models[M]['id'], Models[M]>>(new Map());
  list = $derived([...this.items.values()]);

  get(id: Models[M]['id']): Models[M] | undefined {
    return this.items.get(id);
  }

  apply(message: SubscriptionMessage<M>): void {
    this.items = applyMessage<Models[M]>(this.items, message);
  }
}
