<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Tone } from '../../lib/format';

  interface Props {
    tone?: Tone;
    /** sm: a label in text; md: as tall as a small button, to stand in for one. */
    size?: 'sm' | 'md';
    title?: string;
    children: Snippet;
  }

  let { tone = 'neutral', size = 'sm', title, children }: Props = $props();
</script>

<span class="badge {tone} {size}" {title}>{@render children()}</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    max-width: 100%;
    padding: 1px 7px;
    border-radius: var(--radius-full);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    line-height: 1.5;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .md {
    justify-content: center;
    height: var(--control-height-sm);
    padding: 0 var(--space-2);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
  }

  .neutral {
    background: var(--color-surface-sunken);
    color: var(--color-text-muted);
  }

  .accent {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .success {
    background: var(--color-success-soft);
    color: var(--color-success-text);
  }

  .warning {
    background: var(--color-warning-soft);
    color: var(--color-warning-text);
  }

  .caution {
    background: var(--color-caution-soft);
    color: var(--color-caution-text);
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger-text);
  }
</style>
