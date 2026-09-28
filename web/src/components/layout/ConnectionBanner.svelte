<script lang="ts">
  import { clock } from '../../lib/stores/clock.svelte';
  import { connection, serverSettings } from '../../lib/stores';
  import Button from '../ui/Button.svelte';
  import Notice from '../ui/Notice.svelte';

  // Data stays on screen after a disconnect until the next snapshot replaces it.
  const hasData = $derived(serverSettings.current !== null);
  const retryIn = $derived(
    connection.retryAt === null
      ? 0
      : Math.max(0, Math.ceil((connection.retryAt - clock.now) / 1000)),
  );
</script>

{#if connection.status === 'offline'}
  <div class="banner">
    <Notice tone="danger" icon="offline">
      {#snippet actions()}
        <Button size="sm" onclick={() => connection.reconnectNow()}>Retry now</Button>
      {/snippet}
      {hasData
        ? 'Lost connection to the server. Showing the last known state.'
        : 'Cannot reach the server.'}
      {retryIn > 0 ? `Retrying in ${retryIn} s.` : 'Retrying…'}
    </Notice>
  </div>
{:else if connection.status === 'connecting' && hasData}
  <div class="banner">
    <Notice tone="warning" icon="offline">Reconnecting to the server…</Notice>
  </div>
{/if}

<style>
  .banner {
    padding: var(--space-2) var(--space-2) 0;
  }

  @media (min-width: 760px) {
    .banner {
      padding: var(--space-2) var(--space-3) 0;
    }
  }
</style>
