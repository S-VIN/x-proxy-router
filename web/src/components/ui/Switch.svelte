<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import Spinner from './Spinner.svelte';

  interface Props extends Omit<HTMLButtonAttributes, 'onchange' | 'children'> {
    checked: boolean;
    /** Text before the switch; also its accessible name. */
    label: string;
    /** Shows a spinner and blocks clicks while the change is applied. */
    busy?: boolean;
    /** Shown instead of the label on narrow windows; the label stays the accessible name. */
    shortLabel?: string;
    /** Called with the new state; the owner decides whether `checked` follows. */
    onchange?: (checked: boolean) => void;
  }

  let { checked, label, busy = false, shortLabel, onchange, disabled, ...rest }: Props = $props();
</script>

<button
  type="button"
  role="switch"
  class="switch"
  aria-checked={checked}
  disabled={disabled || busy}
  aria-busy={busy || undefined}
  onclick={() => onchange?.(!checked)}
  {...rest}
>
  {#if busy}
    <Spinner size={14} />
  {/if}
  <span class="label" class:long={shortLabel}>{label}</span>
  {#if shortLabel}
    <span class="label short" aria-hidden="true">{shortLabel}</span>
  {/if}
  <span class="track" class:on={checked}><span class="thumb"></span></span>
</button>

<style>
  .switch {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: var(--space-2);
    height: var(--control-height-sm);
    padding: 0 var(--space-1) 0 var(--space-2);
    border: none;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--color-text);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    white-space: nowrap;
    transition:
      background-color var(--duration-fast) var(--easing),
      opacity var(--duration-fast) var(--easing);
  }

  .switch:not(:disabled):hover {
    background: var(--color-hover);
  }

  .switch:disabled {
    opacity: 0.5;
  }

  .switch[aria-busy='true'] {
    opacity: 0.8;
  }

  .label {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* A libadwaita-style switch: the thumb slides right and the track takes the accent. */
  .track {
    position: relative;
    flex-shrink: 0;
    width: 34px;
    height: 20px;
    border-radius: var(--radius-full);
    background: var(--color-control-active);
    transition: background-color var(--duration-fast) var(--easing);
  }

  .track.on {
    background: var(--color-accent);
  }

  .thumb {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--color-text-on-accent);
    box-shadow: 0 1px 2px var(--color-border-strong);
    transition: transform var(--duration-fast) var(--easing);
  }

  .track.on .thumb {
    transform: translateX(14px);
  }

  .short {
    display: none;
  }

  @media (max-width: 479px) {
    .long {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
    }

    .short {
      display: inline;
    }
  }
</style>
