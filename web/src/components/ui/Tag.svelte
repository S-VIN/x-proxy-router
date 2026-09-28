<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    /** Categorical color 1…TAG_COLORS; null is gray. */
    color: number | null;
    title?: string;
    children: Snippet;
  }

  let { color, title, children }: Props = $props();
</script>

<!-- A colored label that tells items apart, e.g. which subscription a server is from. -->
<span
  class="tag"
  style:--tag-solid={color === null ? null : `var(--color-tag-${color})`}
  style:--tag-soft={color === null ? null : `var(--color-tag-${color}-soft)`}
  style:--tag-text={color === null ? null : `var(--color-tag-${color}-text)`}
  {title}
>
  <span class="swatch" aria-hidden="true"></span>
  <span class="text">{@render children()}</span>
</span>

<style>
  .tag {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    max-width: 100%;
    min-width: 0;
    padding: 0 7px 0 6px;
    border-radius: var(--radius-sm);
    background: var(--tag-soft, var(--color-surface-sunken));
    color: var(--tag-text, var(--color-text-muted));
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    line-height: 1.6;
    white-space: nowrap;
  }

  .swatch {
    flex-shrink: 0;
    width: 7px;
    height: 7px;
    border-radius: 2px;
    background: var(--tag-solid, var(--color-text-faint));
  }

  .text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
