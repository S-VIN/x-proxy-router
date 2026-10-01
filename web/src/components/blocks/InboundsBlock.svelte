<script lang="ts">
  import type { InboundType } from '../../lib/api/protocol';
  import { INBOUND_TYPES } from '../../lib/inbounds';
  import { connection, inboundServers, serverSettings } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import Button from '../ui/Button.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import InboundForm from './inbounds/InboundForm.svelte';
  import InboundItem from './inbounds/InboundItem.svelte';

  let { order }: { order: number } = $props();

  // Snapshots of all models come together; settings are the first of them.
  const loading = $derived(serverSettings.current === null);
  // The type of the inbound being added, if any.
  let adding = $state<InboundType | null>(null);
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
      {#if adding !== null}
        <InboundForm
          inbound={null}
          type={adding}
          ready={connection.ready}
          onclose={() => (adding = null)}
        />
      {:else}
        <!-- A button per type, so a new type is one more button. -->
        <div class="types">
          {#each INBOUND_TYPES as info (info.type)}
            <Button
              variant="primary"
              size="sm"
              icon="add"
              title={info.description}
              disabled={!connection.ready}
              onclick={() => (adding = info.type)}
            >
              Add {info.label.toLowerCase()}
            </Button>
          {/each}
        </div>
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

  .types {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
