<script lang="ts" module>
  export interface Option<V extends string> {
    value: V;
    label: string;
  }
</script>

<script lang="ts" generics="T extends string">
  import type { HTMLSelectAttributes } from 'svelte/elements';
  import Icon from './Icon.svelte';

  interface Props extends Omit<HTMLSelectAttributes, 'value' | 'size'> {
    value: T;
    options: readonly Option<T>[];
    size?: 'md' | 'sm';
    /** As wide as the chosen option, without a background until hovered: for block headers. */
    inline?: boolean;
  }

  let { value = $bindable(), options, size = 'md', inline = false, ...rest }: Props = $props();

  const chosen = $derived(options.find((option) => option.value === value)?.label ?? '');
</script>

<div class="select {size}" class:inline>
  {#if inline}
    <!-- Sizes the control; the select on top of it shows the same text. -->
    <span class="sizer" aria-hidden="true">{chosen}</span>
  {/if}
  <select bind:value {...rest}>
    {#each options as option (option.value)}
      <option value={option.value}>{option.label}</option>
    {/each}
  </select>
  <span class="chevron"><Icon name="chevron-down" size={inline ? 12 : 16} /></span>
</div>

<style>
  .select {
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
  }

  select {
    width: 100%;
    min-width: 0;
    height: var(--control-height);
    padding: 0 calc(var(--space-3) + 16px + var(--space-1)) 0 var(--space-3);
    border: none;
    border-radius: var(--radius-md);
    background: var(--color-control);
    font-weight: var(--weight-medium);
    text-overflow: ellipsis;
    appearance: none;
    cursor: pointer;
    transition: background-color var(--duration-fast) var(--easing);
  }

  select:hover:not(:disabled) {
    background: var(--color-control-hover);
  }

  select:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .sm select {
    height: var(--control-height-sm);
    padding-left: var(--space-2);
    font-size: var(--text-sm);
  }

  .chevron {
    position: absolute;
    right: var(--space-3);
    color: var(--color-text-muted);
    pointer-events: none;
  }

  .sm .chevron {
    right: var(--space-2);
  }

  .inline {
    flex-shrink: 0;
  }

  .sizer,
  .inline select {
    padding: 0 calc(var(--space-1) + 12px + var(--space-1)) 0 6px;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    white-space: nowrap;
  }

  .sizer {
    line-height: var(--control-height-sm);
    visibility: hidden;
  }

  .inline select {
    position: absolute;
    inset: 0;
    height: auto;
    background: transparent;
  }

  .inline select:hover:not(:disabled) {
    background: var(--color-hover);
  }

  .inline .chevron {
    right: var(--space-1);
  }
</style>
