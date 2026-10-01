<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { RegFilter } from '../../../lib/api/protocol';
  import { regFilters } from '../../../lib/stores';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';

  let { filter, ready }: { filter: RegFilter; ready: boolean } = $props();

  let deleting = $state(false);
  let error = $state<string | null>(null);

  async function remove() {
    deleting = true;
    error = null;
    try {
      await regFilters.remove(filter.id);
    } catch (reason) {
      error = describeError(reason, { not_found: 'This filter was already removed.' });
      deleting = false;
    }
  }
</script>

<li class="item">
  <div class="line">
    <code class="reg" title={filter.reg}>{filter.reg}</code>
    <Button
      variant="flat"
      size="sm"
      icon="trash"
      label="Remove filter"
      busy={deleting}
      disabled={!ready}
      onclick={remove}
    />
  </div>
  {#if error}
    <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
  {/if}
</li>

<style>
  .item {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .line {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--control-height-sm);
  }

  /* Spaces are part of the expression, so they are kept. */
  .reg {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    text-overflow: ellipsis;
    white-space: pre;
  }
</style>
