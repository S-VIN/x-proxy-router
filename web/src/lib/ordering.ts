import type { OutboundServer } from './api/protocol';

export type SortKey = 'rating' | 'ping' | 'speed' | 'name';

export const SORT_LABELS: Record<SortKey, string> = {
  rating: 'Rating',
  ping: 'Ping',
  speed: 'Speed',
  name: 'Name',
};

const byName = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

/** Ascending numbers with null last. */
function ascending(a: number | null, b: number | null): number {
  if (a === b) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a - b;
}

/** Descending numbers with null last. */
function descending(a: number | null, b: number | null): number {
  if (a === b) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return b - a;
}

function names(a: OutboundServer, b: OutboundServer): number {
  return byName.compare(a.name, b.name) || a.id.localeCompare(b.id);
}

export const COMPARATORS: Record<SortKey, (a: OutboundServer, b: OutboundServer) => number> = {
  rating: (a, b) => descending(a.rating, b.rating) || ascending(a.ping, b.ping) || names(a, b),
  ping: (a, b) => ascending(a.ping, b.ping) || descending(a.rating, b.rating) || names(a, b),
  speed: (a, b) => descending(a.speed, b.speed) || descending(a.rating, b.rating) || names(a, b),
  name: names,
};

/**
 * Keep items in a previous order: known ids stay where they were, items that
 * disappeared are dropped and new ones follow, sorted by `compare`.
 */
export function keepOrder<T extends { id: string }>(
  previous: readonly string[],
  items: readonly T[],
  compare: (a: T, b: T) => number,
): T[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  const result: T[] = [];
  for (const id of previous) {
    const item = byId.get(id);
    if (item) {
      result.push(item);
      byId.delete(id);
    }
  }
  return result.concat([...byId.values()].sort(compare));
}
