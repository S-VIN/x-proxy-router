<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import Icon, { type IconName } from './Icon.svelte';
  import Spinner from './Spinner.svelte';

  interface Props extends HTMLButtonAttributes {
    /** default: neutral; primary: the main action; flat: no background; danger: destructive. */
    variant?: 'default' | 'primary' | 'flat' | 'danger';
    size?: 'md' | 'sm';
    icon?: IconName;
    /** Shows a spinner and blocks clicks while an action runs. */
    busy?: boolean;
    /** Accessible name and tooltip; required for icon-only buttons. */
    label?: string;
    children?: Snippet;
  }

  let {
    variant = 'default',
    size = 'md',
    icon,
    busy = false,
    label,
    children,
    disabled,
    type = 'button',
    ...rest
  }: Props = $props();
</script>

<button
  {type}
  class="button {variant} {size}"
  class:icon-only={!children}
  disabled={disabled || busy}
  aria-busy={busy || undefined}
  aria-label={label}
  title={label}
  {...rest}
>
  {#if busy}
    <Spinner />
  {:else if icon}
    <Icon name={icon} />
  {/if}
  {#if children}
    <span class="text">{@render children()}</span>
  {/if}
</button>

<style>
  .button {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    height: var(--control-height);
    padding: 0 var(--space-4);
    border: none;
    border-radius: var(--radius-md);
    background: var(--color-control);
    color: var(--color-text);
    font-weight: var(--weight-medium);
    white-space: nowrap;
    transition:
      background-color var(--duration-fast) var(--easing),
      opacity var(--duration-fast) var(--easing);
  }

  .button:not(:disabled):hover {
    background: var(--color-control-hover);
  }

  .button:not(:disabled):active {
    background: var(--color-control-active);
  }

  .button:disabled {
    opacity: 0.5;
  }

  .button[aria-busy='true'] {
    opacity: 0.8;
  }

  .sm {
    height: var(--control-height-sm);
    padding: 0 var(--space-3);
    font-size: var(--text-sm);
  }

  .icon-only {
    width: var(--control-height);
    padding: 0;
  }

  .icon-only.sm {
    width: var(--control-height-sm);
  }

  .primary {
    background: var(--color-accent);
    color: var(--color-text-on-accent);
  }

  .primary:not(:disabled):hover {
    background: var(--color-accent-strong);
  }

  .primary:not(:disabled):active {
    background: var(--color-accent-pressed);
  }

  .flat {
    background: transparent;
  }

  .danger {
    background: var(--color-danger);
    color: var(--color-text-on-accent);
  }

  .danger:not(:disabled):hover {
    background: var(--color-danger-strong);
  }

  .danger:not(:disabled):active {
    background: var(--color-danger-strong);
  }

  .text {
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
