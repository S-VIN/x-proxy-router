<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { OutboundServer, OutboundTest } from '../../../lib/api/protocol';
  import { outboundServers } from '../../../lib/stores';
  import Badge from '../../ui/Badge.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
  import Meter from '../../ui/Meter.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Tag from '../../ui/Tag.svelte';
  import ServerDetails from './ServerDetails.svelte';
  import TestResults from './TestResults.svelte';

  interface Props {
    server: OutboundServer;
    tests: readonly OutboundTest[];
    /** Label and tag color of the server's subscription. */
    subscription: string;
    subscriptionColor: number | null;
    expanded: boolean;
    ontoggle: () => void;
    /** Requests can be sent. */
    ready: boolean;
  }

  let { server, tests, subscription, subscriptionColor, expanded, ontoggle, ready }: Props =
    $props();

  const id = $props.id();
  let connecting = $state(false);
  let error = $state<string | null>(null);

  async function connect() {
    connecting = true;
    error = null;
    try {
      await outboundServers.connect(server.id);
    } catch (reason) {
      error = describeError(reason, {
        core_error:
          'The proxy core could not switch to this server. The previous one is still used.',
        not_found: 'This server disappeared after a subscription update.',
      });
    } finally {
      connecting = false;
    }
  }
</script>

<li class="row" class:connected={server.is_connected} class:expanded>
  <div class="line">
    <button
      type="button"
      class="summary"
      aria-expanded={expanded}
      aria-controls={expanded ? id : undefined}
      onclick={ontoggle}
    >
      <span class="name" title={server.name}>{server.name}</span>
      <span class="subscription">
        <Tag color={subscriptionColor} title={subscription}>{subscription}</Tag>
      </span>
      <span class="metrics">
        <span class="metric rating"><Meter value={server.rating} label="Rating" /></span>
        <span class="metric tests">
          <span class="visually-hidden">Tests</span>
          <TestResults results={server.tests} {tests} />
        </span>
      </span>
      <span class="chevron" class:open={expanded}><Icon name="chevron-down" size={14} /></span>
    </button>
    <div class="action">
      {#if server.is_connected}
        <Badge tone="success">Connected</Badge>
      {:else}
        <Button size="sm" busy={connecting} disabled={!ready} onclick={connect}>Connect</Button>
      {/if}
    </div>
  </div>
  {#if error}
    <div class="error">
      <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
    </div>
  {/if}
  {#if expanded}
    <ServerDetails {id} {server} {subscription} {tests} />
  {/if}
</li>

<style>
  .row {
    border-top: 1px solid var(--color-border);
  }

  .row.connected {
    background: var(--color-accent-soft);
    box-shadow: inset 3px 0 0 var(--color-accent);
  }

  .line {
    display: grid;
    grid-template-columns: minmax(0, 1fr) var(--action-width);
    align-items: center;
    min-height: 32px;
  }

  .line:hover {
    background: var(--color-hover);
  }

  /* One line; the columns are shared with the header in ServersBlock. */
  .summary {
    display: grid;
    grid-template-columns: var(--server-columns);
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    padding: 3px var(--space-3);
    border: none;
    background: none;
    text-align: left;
  }

  .summary:focus-visible {
    outline-offset: -2px;
  }

  .name {
    overflow: hidden;
    font-weight: var(--weight-medium);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .subscription {
    display: flex;
    min-width: 0;
  }

  .metrics {
    display: contents;
  }

  .metric {
    min-width: 0;
    font-size: var(--text-sm);
  }

  .tests {
    display: flex;
    align-items: center;
  }

  .chevron {
    color: var(--color-text-faint);
    transition: transform var(--duration-fast) var(--easing);
  }

  .chevron.open {
    transform: rotate(180deg);
  }

  .action {
    display: flex;
    justify-content: flex-end;
    padding-right: var(--space-2);
  }

  .error {
    padding: 0 var(--space-3) var(--space-2);
  }

  /* The same widths are in ServersBlock. */
  @container block (width < 500px) {
    .chevron {
      display: none;
    }
  }

  /* Narrow block: name and subscription on the first line, rating and tests on the second. */
  @container block (width < 460px) {
    .summary {
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0 var(--space-2);
      line-height: 1.3;
    }

    .subscription {
      max-width: 9rem;
    }

    .metrics {
      display: flex;
      grid-column: 1 / -1;
      align-items: center;
      gap: var(--space-3);
    }

    .rating {
      flex: 0 1 96px;
      min-width: 56px;
    }
  }
</style>
