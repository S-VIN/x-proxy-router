<script lang="ts">
  import Icon from './Icon.svelte';

  let { text }: { text: string } = $props();
</script>

<!-- Explanations stay out of the way: the text shows on hover and is read by screen readers. -->
<span class="hint" role="img" aria-label={text} title={text}>
  <Icon name="info" size={14} />
</span>

<style>
  .hint {
    display: inline-flex;
    flex-shrink: 0;
    color: var(--color-text-faint);
    cursor: help;
  }

  .hint:hover {
    color: var(--color-text-muted);
  }
</style>
