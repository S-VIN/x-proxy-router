<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { OutboundTest } from '../../../lib/api/protocol';
  import { hostLabel, ruleLabel } from '../../../lib/format';
  import { outboundTests } from '../../../lib/stores';
  import Badge from '../../ui/Badge.svelte';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';

  interface Props {
    test: OutboundTest;
    /** The site name the test goes by. */
    label: string;
    ready: boolean;
  }

  let { test, label, ready }: Props = $props();

  let deleting = $state(false);
  let error = $state<string | null>(null);

  async function remove() {
    deleting = true;
    error = null;
    try {
      await outboundTests.remove(test.id);
    } catch (reason) {
      error = describeError(reason, { not_found: 'This test was already deleted.' });
      deleting = false;
    }
  }
</script>

<li class="item">
  <!-- Name, URL and rule on one line; the whole URL is in the tooltip. -->
  <div class="line" title={`${test.url}\nPasses: ${ruleLabel(test.rule)}`}>
    <span class="name">{label}</span>
    <span class="url">{hostLabel(test.url)}</span>
    <Badge>{ruleLabel(test.rule)}</Badge>
    <Button
      variant="flat"
      size="sm"
      icon="trash"
      label="Delete test"
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
    display: grid;
    grid-template-columns: minmax(0, auto) minmax(0, 1fr) auto auto;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--control-height-sm);
  }

  .name {
    max-width: 8rem;
    overflow: hidden;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .url {
    overflow: hidden;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
