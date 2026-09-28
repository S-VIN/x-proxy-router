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
  }

  let { value = $bindable(), options, size = 'md', ...rest }: Props = $props();
</script>

<div class="select {size}">
  <select bind:value {...rest}>
    {#each options as option (option.value)}
      <option value={option.value}>{option.label}</option>
    {/each}
  </select>
  <span class="chevron"><Icon name="chevron-down" /></span>
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
</style>
