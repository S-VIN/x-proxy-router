<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon, { type IconName } from './Icon.svelte';

  interface Props {
    tone?: 'info' | 'warning' | 'danger';
    icon?: IconName;
    /** Buttons shown after the text. */
    actions?: Snippet;
    /** Shows a close button. */
    ondismiss?: () => void;
    children: Snippet;
  }

  let { tone = 'info', icon, actions, ondismiss, children }: Props = $props();

  const defaultIcons: Record<string, IconName> = {
    info: 'info',
    warning: 'alert',
    danger: 'alert',
  };
</script>

<div class="notice {tone}" role={tone === 'danger' ? 'alert' : 'status'}>
  <span class="icon"><Icon name={icon ?? defaultIcons[tone] ?? 'info'} /></span>
  <div class="body">
    <div class="text">{@render children()}</div>
    {#if actions}
      <div class="actions">{@render actions()}</div>
    {/if}
  </div>
  {#if ondismiss}
    <button class="dismiss" type="button" aria-label="Dismiss" title="Dismiss" onclick={ondismiss}>
      <Icon name="close" size={14} />
    </button>
  {/if}
</div>

<style>
  .notice {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
  }

  .icon {
    padding-top: 2px;
  }

  .body {
    display: flex;
    flex: 1;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    min-width: 0;
  }

  .text {
    flex: 1 1 12em;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    gap: var(--space-2);
  }

  .info {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .warning {
    background: var(--color-warning-soft);
    color: var(--color-warning-text);
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger-text);
  }

  .dismiss {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    margin: -1px -4px 0 0;
    padding: 0;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: inherit;
  }

  .dismiss:hover {
    background: var(--color-control);
  }
</style>
