<script lang="ts">
  import type { Snippet } from 'svelte';
  import Hint from '../ui/Hint.svelte';
  import Icon, { type IconName } from '../ui/Icon.svelte';

  interface Props {
    title: string;
    icon?: IconName;
    /** Position among all blocks when the zones collapse into fewer columns. */
    order: number;
    /** Short text after the title, e.g. a count. */
    meta?: string;
    /** Explanation shown on hover over an info icon next to the title. */
    hint?: string;
    /** Take the zone's full height and let the content scroll inside (wide layouts). */
    fill?: boolean;
    /** No padding around the content, for full-width lists. */
    flush?: boolean;
    /** Controls on the right of the title. */
    actions?: Snippet;
    children: Snippet;
  }

  let {
    title,
    icon,
    order,
    meta,
    hint,
    fill = false,
    flush = false,
    actions,
    children,
  }: Props = $props();

  const id = $props.id();
</script>

<section class="block" class:fill class:flush style:--block-order={order} aria-labelledby={id}>
  <header class="header">
    {#if icon}
      <span class="icon"><Icon name={icon} /></span>
    {/if}
    <h2 class="title" {id}>{title}</h2>
    {#if meta}
      <span class="meta num">{meta}</span>
    {/if}
    {#if hint}
      <Hint text={hint} />
    {/if}
    {#if actions}
      <div class="actions">{@render actions()}</div>
    {/if}
  </header>
  <div class="body">
    {@render children()}
  </div>
</section>

<style>
  .block {
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    order: var(--block-order);
    min-width: 0;
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    box-shadow: var(--shadow-card);
  }

  .header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    min-height: calc(var(--control-height-sm) + var(--space-2));
    padding: var(--space-2) var(--space-2) 0 var(--space-3);
  }

  .icon {
    color: var(--color-text-muted);
  }

  .title {
    font-size: var(--text-md);
  }

  .meta {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    padding: var(--space-2) var(--space-3) var(--space-3);
    container: block / inline-size;
  }

  .flush .body {
    padding: var(--space-2) 0 0;
  }

  @media (min-width: 760px) {
    .fill {
      flex: 1 1 auto;
      min-height: 0;
    }

    .fill .body {
      flex: 1 1 auto;
      min-height: 0;
    }
  }
</style>
