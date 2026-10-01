<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Tone } from '../../lib/format';

  interface Props {
    label: string;
    tone?: Tone;
    children: Snippet;
  }

  let { label, tone = 'neutral', children }: Props = $props();
</script>

<div class="stat {tone}">
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
