<script lang="ts">
  import { connection, outboundTests, serverSettings } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import AddTestForm from './tests/AddTestForm.svelte';
  import TestItem from './tests/TestItem.svelte';

  let { order }: { order: number } = $props();

  // Snapshots of all models come together; settings are the first of them.
  const loading = $derived(serverSettings.current === null);
</script>

<Block
  title="Tests"
  icon="tests"
  {order}
  meta={loading ? undefined : String(outboundTests.list.length)}
  hint="Every server check requests these URLs through the server. A test passes when the response status matches its rule; redirects are not followed. A test is named after its site; new tests run from the next check."
>
  {#if loading}
    <EmptyState compact loading title="Loading…" />
  {:else}
    {#if outboundTests.list.length === 0}
      <p class="muted small" title="Servers are rated by ping and speed only.">No tests</p>
    {:else}
      <ul class="list">
        {#each outboundTests.list as test (test.id)}
          <TestItem {test} label={outboundTests.label(test.id)} ready={connection.ready} />
        {/each}
      </ul>
    {/if}
    <AddTestForm ready={connection.ready} />
  {/if}
</Block>

<style>
  .list {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
