import type { Connection } from '../api/connection.svelte';
import type { SubscriptionLink } from '../api/protocol';
import { siteLabels, TAG_COLORS } from '../format';
import { Collection } from './collection.svelte';

/** Short names for links: the site name, numbered when several links share it. */
export function linkLabels(links: readonly SubscriptionLink[]): Map<string, string> {
  return siteLabels(links, (link) => link.url_short);
}

/** A tag color (1…count) for each link, in list order; they repeat after count links. */
export function linkColors(
  links: readonly SubscriptionLink[],
  count = TAG_COLORS,
): Map<string, number> {
  return new Map(links.map((link, index) => [link.id, (index % count) + 1]));
}

/**
 * Provider subscription links, added, moved and deleted; a URL never changes. Full
 * URLs are secret: only url_short comes back. The server renumbers the other links
 * itself when one is added, moved or deleted.
 */
export class SubscriptionLinksStore {
  #connection: Connection;
  #collection = new Collection<'subscription_link'>();
  /** In the order they were added, new links last; labels and colors follow it, so moves keep them. */
  list = $derived(this.#collection.list);
  /** In priority order, the preferred one first. */
  byPriority = $derived([...this.list].sort((a, b) => a.priority - b.priority));
  labels = $derived(linkLabels(this.list));
  colors = $derived(linkColors(this.list));

  constructor(connection: Connection) {
    this.#connection = connection;
    connection.on('subscription_link', (message) => this.#collection.apply(message));
  }

  label(id: string | null): string {
    if (id === null) return 'No subscription';
    return this.labels.get(id) ?? 'Removed subscription';
  }

  /** Tag color of the link; null for servers without a known subscription. */
  color(id: string | null): number | null {
    return id === null ? null : (this.colors.get(id) ?? null);
  }

  /** Adds the link and reloads servers of all subscriptions; resolves after that. */
  add(url: string) {
    return this.#connection.request('add/subscription_link', { url });
  }

  /** Puts the link at the priority; the links in between shift towards its old place. */
  move(id: string, priority: number) {
    return this.#connection.request('change/subscription_link', { id, priority });
  }

  /** Removes the link; its servers stay until the next refresh. */
  remove(id: string) {
    return this.#connection.request('delete/subscription_link', { id });
  }
}
