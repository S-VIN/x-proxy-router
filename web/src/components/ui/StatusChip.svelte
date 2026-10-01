<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Tone } from '../../lib/format';
  import StatusDot from './StatusDot.svelte';

  interface Props {
    /** A colored dot in front. */
    dot?: Tone;
    pulse?: boolean;
    title?: string;
    children: Snippet;
  }

  let { dot, pulse = false, title, children }: Props = $props();
</script>

<span class="chip" {title}>
  {#if dot}
    <StatusDot tone={dot} {pulse} />
  {/if}
  <span class="text">{@render children()}</span>
</span>

<style>
  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    height: var(--control-height-sm);
    padding: 0 var(--space-3);
    border-radius: var(--radius-full);
    background: var(--color-control);
    font-size: var(--text-sm);
    white-space: nowrap;
  }

  .text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
