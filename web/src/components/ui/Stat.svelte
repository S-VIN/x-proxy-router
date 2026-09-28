<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Tone } from '../../lib/format';

  interface Props {
    label: string;
    tone?: Tone;
    /** A framed stat with a larger value, for the key figures of a card. */
    tile?: boolean;
    children: Snippet;
  }

  let { label, tone = 'neutral', tile = false, children }: Props = $props();
</script>

<div class="stat {tone}" class:tile>
  <dt class="label">{label}</dt>
  <dd class="value num">{@render children()}</dd>
</div>

<style>
  .stat {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .label {
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
  }

  .value {
    overflow: hidden;
    font-size: var(--text-sm);
    font-weight: var(--weight-bold);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tile {
    gap: 1px;
    padding: 6px 10px;
    border-radius: var(--radius-md);
    background: var(--color-surface);
    box-shadow: 0 0 0 1px var(--color-border);
  }

  .tile .value {
    font-size: var(--text-lg);
  }

  .success .value {
    color: var(--color-success-text);
  }

  .warning .value {
    color: var(--color-warning-text);
  }

  .caution .value {
    color: var(--color-caution-text);
  }

  .danger .value {
    color: var(--color-danger-text);
  }
</style>
