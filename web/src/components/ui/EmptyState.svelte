<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon, { type IconName } from './Icon.svelte';
  import Spinner from './Spinner.svelte';

  interface Props {
    title: string;
    icon?: IconName;
    /** Shows a spinner instead of the icon. */
    loading?: boolean;
    compact?: boolean;
    /** Explanation shown on hover. */
    hint?: string;
    children?: Snippet;
  }

  let { title, icon, loading = false, compact = false, hint, children }: Props = $props();
</script>

<div class="empty" class:compact title={hint}>
  {#if loading}
    <span class="icon"><Spinner size={compact ? 16 : 28} /></span>
  {:else if icon}
    <span class="icon"><Icon name={icon} size={compact ? 16 : 28} /></span>
  {/if}
  <p class="title">{title}</p>
  {#if children}
    <div class="text">{@render children()}</div>
  {/if}
</div>

<style>
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-6) var(--space-4);
    text-align: center;
  }

  .compact {
    flex-direction: row;
    justify-content: center;
    padding: var(--space-2);
    color: var(--color-text-muted);
  }

  .icon {
    color: var(--color-text-faint);
  }

  .title {
    font-weight: var(--weight-bold);
  }

  .compact .title {
    font-weight: var(--weight-medium);
  }

  .text {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    max-width: 36ch;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
</style>
