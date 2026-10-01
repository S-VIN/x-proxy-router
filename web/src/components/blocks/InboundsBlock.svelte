<script lang="ts">
  import { connection, inboundServers, serverSettings } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import Button from '../ui/Button.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import InboundForm from './inbounds/InboundForm.svelte';
  import InboundItem from './inbounds/InboundItem.svelte';

  let { order }: { order: number } = $props();

  // Snapshots of all models come together; settings are the first of them.
  const loading = $derived(serverSettings.current === null);
  let adding = $state(false);
</script>

<Block
  title="Inbounds"
  icon="inbound"
  {order}
  meta={loading ? undefined : String(inboundServers.list.length)}
  hint="Ports where apps send their traffic, e.g. a browser with this proxy in its settings. The traffic goes by the routing rules; the rest goes through the connected server and is blocked while none is connected."
>
  {#if loading}
    <EmptyState compact loading title="Loading…" />
  {:else}
    {#if inboundServers.list.length === 0}
      <p class="muted small" title="Apps cannot send traffic through the router until you add one.">
        No inbounds
      </p>
    {:else}
      <ul class="list">
        {#each inboundServers.list as inbound (inbound.id)}
          <InboundItem {inbound} ready={connection.ready} />
        {/each}
      </ul>
    {/if}
    <div class="add">
      {#if adding}
        <InboundForm inbound={null} ready={connection.ready} onclose={() => (adding = false)} />
      {:else}
        <Button
          variant="flat"
          size="sm"
          icon="add"
          disabled={!connection.ready}
          onclick={() => (adding = true)}
        >
          Add inbound
        </Button>
      {/if}
    </div>
  {/if}
</Block>

<style>
  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .add {
    display: flex;
    flex-direction: column;
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }

  .add > :global(button) {
    align-self: flex-start;
  }
</style>
