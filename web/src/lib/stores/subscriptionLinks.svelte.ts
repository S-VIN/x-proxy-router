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
 * Provider subscription links, added and deleted but never changed. Full URLs are
 * secret: only url_short comes back.
 */
export class SubscriptionLinksStore {
  #connection: Connection;
  #collection = new Collection<'subscription_link'>();
  /** In server order; new links come last. */
  list = $derived(this.#collection.list);
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

  /** Removes the link; its servers stay until the next refresh. */
  remove(id: string) {
    return this.#connection.request('delete/subscription_link', { id });
  }
}
