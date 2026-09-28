<script lang="ts">
  import { formatPing, pingTone } from '../../lib/format';
  import { logoUrl } from '../../lib/logo';
  import { connection, linkStatus, outboundServers, serverSettings } from '../../lib/stores';
  import StatusChip from '../ui/StatusChip.svelte';

  const current = $derived(outboundServers.connected);
  const statusText = $derived(
    { online: 'Online', connecting: 'Connecting…', offline: 'Offline' }[connection.status],
  );
</script>

<header class="header">
  <!-- Blue: no server connected; green: connected; red: an error. -->
  <img
    class="logo"
    src={logoUrl(linkStatus.state)}
    alt="x-proxy-router: {linkStatus.description}"
    title={linkStatus.description}
    width="28"
    height="28"
  />
  <div class="status" aria-label="Status">
    {#if serverSettings.current}
      {#if current}
        <StatusChip dot={pingTone(current.ping)} title="Traffic goes through {current.name}">
          {current.name}{#if current.ping !== null}<span class="muted"
              >{` · ${formatPing(current.ping)}`}</span
            >{/if}
        </StatusChip>
      {:else}
        <StatusChip dot="neutral" title="No server is selected">No server</StatusChip>
      {/if}
    {/if}
    <StatusChip
      dot={connection.status === 'online'
        ? 'success'
        : connection.status === 'offline'
          ? 'danger'
          : 'warning'}
      pulse={connection.status === 'connecting'}
      collapsible
      title="Connection to the x-proxy-router server: {statusText}"
    >
      {statusText}
    </StatusChip>
  </div>
</header>

<style>
  .header {
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: var(--space-3);
    height: var(--header-height);
    padding: 0 var(--space-3);
    background: var(--color-header);
    box-shadow: var(--shadow-header);
    backdrop-filter: blur(12px);
  }

  .logo {
    display: block;
    flex-shrink: 0;
  }

  .status {
    display: flex;
    flex: 1;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-2);
    min-width: 0;
  }
</style>
