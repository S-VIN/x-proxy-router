<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { SubscriptionLink } from '../../../lib/api/protocol';
  import { plural } from '../../../lib/format';
  import { subscriptionLinks } from '../../../lib/stores';
  import Button from '../../ui/Button.svelte';
  import MoveArrows from '../../ui/MoveArrows.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Tag from '../../ui/Tag.svelte';

  interface Props {
    link: SubscriptionLink;
    label: string;
    /** Tag color, the same as on its servers. */
    color: number | null;
    /** Number of servers loaded from this link. */
    servers: number;
    /** Number of links, the last priority it can move to. */
    count: number;
    ready: boolean;
  }

  let { link, label, color, servers, count, ready }: Props = $props();

  let moving = $state(false);
  let deleting = $state(false);
  let error = $state<string | null>(null);

  /** Swaps the link with its neighbour: the server shifts the links in between. */
  async function move(step: -1 | 1) {
    moving = true;
    error = null;
    try {
      await subscriptionLinks.move(link.id, link.priority + step);
    } catch (reason) {
      error = describeError(reason, {
        not_found: 'This subscription was deleted.',
        validation_error: 'The subscriptions changed meanwhile. Try again.',
      });
    } finally {
      moving = false;
    }
  }

  async function remove() {
    deleting = true;
    error = null;
    try {
      await subscriptionLinks.remove(link.id);
    } catch (reason) {
      error = describeError(reason, { not_found: 'This subscription was already deleted.' });
      deleting = false;
    }
  }
</script>

<li class="item">
  <div class="line">
    <!-- Auto connect prefers the upper subscriptions; the arrows move this one. -->
    <MoveArrows
      upLabel="Move up: prefer before the subscription above"
      downLabel="Move down: prefer after the subscription below"
      first={link.priority <= 1}
      last={link.priority >= count}
      disabled={!ready || moving || deleting}
      onmove={move}
    />
    <span class="name"><Tag {color} title={link.url_short}>{label}</Tag></span>
    <span class="count num">{plural(servers, 'server')}</span>
    <Button
      variant="flat"
      size="sm"
      icon="trash"
      label="Delete subscription"
      busy={deleting}
      disabled={!ready || moving}
      onclick={remove}
    />
  </div>

  {#if error}
    <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
  {/if}
</li>

<style>
  .item {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .line {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--control-height-sm);
  }

  .name {
    display: flex;
    min-width: 0;
  }

  .count {
    margin-left: auto;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    white-space: nowrap;
  }
</style>
