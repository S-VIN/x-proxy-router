<script lang="ts">
  import Icon from './Icon.svelte';

  interface Props {
    /** Accessible names of the arrows, saying what the move changes. */
    upLabel: string;
    downLabel: string;
    /** The item is at the top or the bottom of its list. */
    first: boolean;
    last: boolean;
    disabled?: boolean;
    onmove: (step: -1 | 1) => void;
  }

  let { upLabel, downLabel, first, last, disabled = false, onmove }: Props = $props();
</script>

<!-- Two small arrows, one above the other, as tall as a list row. -->
<span class="move">
  <button
    type="button"
    class="arrow"
    aria-label={upLabel}
    title="Move up"
    disabled={disabled || first}
    onclick={() => onmove(-1)}
  >
    <Icon name="chevron-up" size={12} />
  </button>
  <button
    type="button"
    class="arrow"
    aria-label={downLabel}
    title="Move down"
    disabled={disabled || last}
    onclick={() => onmove(1)}
  >
    <Icon name="chevron-down" size={12} />
  </button>
</span>

<style>
  .move {
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }

  .arrow {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 13px;
    padding: 0;
    border: none;
    border-radius: var(--radius-sm);
    background: none;
    color: var(--color-text-muted);
    transition: background-color var(--duration-fast) var(--easing);
  }

  .arrow:not(:disabled):hover {
    background: var(--color-control-hover);
    color: var(--color-text);
  }

  .arrow:disabled {
    color: var(--color-text-faint);
    opacity: 0.4;
  }
</style>
