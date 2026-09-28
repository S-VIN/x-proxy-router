<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import Icon, { type IconName } from './Icon.svelte';

  interface Props extends Omit<HTMLInputAttributes, 'value' | 'size'> {
    value?: string;
    size?: 'md' | 'sm';
    /** Shown at the start of the field, e.g. search. */
    icon?: IconName;
    invalid?: boolean;
    /** Focus the field when it appears. */
    autofocus?: boolean;
  }

  let {
    value = $bindable(''),
    size = 'md',
    icon,
    invalid = false,
    autofocus = false,
    type = 'text',
    ...rest
  }: Props = $props();

  function focusOnMount(input: HTMLInputElement) {
    if (autofocus) input.focus();
  }
</script>

<div class="field {size}" class:invalid class:with-icon={icon}>
  {#if icon}
    <span class="icon"><Icon name={icon} /></span>
  {/if}
  <input
    {type}
    bind:value
    aria-invalid={invalid || undefined}
    spellcheck="false"
    autocomplete="off"
    {@attach focusOnMount}
    {...rest}
  />
</div>

<style>
  .field {
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
  }

  input {
    width: 100%;
    min-width: 0;
    height: var(--control-height);
    padding: 0 var(--space-3);
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    background: var(--color-control);
    transition:
      background-color var(--duration-fast) var(--easing),
      box-shadow var(--duration-fast) var(--easing);
  }

  input::placeholder {
    color: var(--color-text-faint);
  }

  input:hover:not(:disabled):not(:focus) {
    background: var(--color-control-hover);
  }

  input:focus {
    outline: none;
    background: var(--color-surface);
    border-color: var(--color-accent);
    box-shadow: 0 0 0 2px var(--color-focus);
  }

  input:disabled {
    opacity: 0.55;
  }

  .with-icon input {
    padding-left: calc(var(--space-3) + 16px + var(--space-2));
  }

  .sm input {
    height: var(--control-height-sm);
    padding: 0 var(--space-2);
    font-size: var(--text-sm);
  }

  .sm.with-icon input {
    padding-left: calc(var(--space-2) + 16px + var(--space-2));
  }

  .sm .icon {
    left: var(--space-2);
  }

  .icon {
    position: absolute;
    left: var(--space-3);
    color: var(--color-text-muted);
    pointer-events: none;
  }

  .invalid input,
  .invalid input:focus {
    border-color: var(--color-danger);
    box-shadow: 0 0 0 2px var(--color-danger-soft);
  }
</style>
