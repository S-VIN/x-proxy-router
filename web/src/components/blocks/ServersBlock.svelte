<script lang="ts">
  import { describeError } from '../../lib/api/errors';
  import type { OutboundServer } from '../../lib/api/protocol';
  import { protocolLabel } from '../../lib/format';
  import {
    COMPARATORS,
    filteredLast,
    keepOrder,
    SORT_LABELS,
    type SortKey,
  } from '../../lib/ordering';
  import {
    connection,
    outboundServers,
    outboundTests,
    regFilters,
    serverSettings,
    subscriptionLinks,
    tasks,
  } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import Button from '../ui/Button.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import Notice from '../ui/Notice.svelte';
  import Select, { type Option } from '../ui/Select.svelte';
  import Switch from '../ui/Switch.svelte';
  import ServerRow from './servers/ServerRow.svelte';

  let { order }: { order: number } = $props();

  const ALL = 'all';
  // Servers of deleted subscriptions stay until the next refresh.
  const OTHER = 'other';

  let subscription = $state(ALL);
  let protocol = $state(ALL);
  let sort = $state<SortKey>('rating');
  let expanded = $state<string | null>(null);
  let checkError = $state<string | null>(null);
  // The state asked for while the request runs; the server's state otherwise.
  let autoConnectPending = $state<boolean | null>(null);
  let autoConnectError = $state<string | null>(null);

  const tests = $derived(outboundTests.list);
  // Room for a mark per test (8px and a 3px gap), at least for the "Tests" heading.
  const testsWidth = $derived(`${Math.max(36, tests.length * 11 - 3)}px`);
  const total = $derived(outboundServers.list.length);
  const loading = $derived(serverSettings.current === null);
  const autoConnect = $derived(serverSettings.current?.auto_connect ?? false);

  function knownSubscription(server: OutboundServer): boolean {
    return server.subscription_id !== null && subscriptionLinks.labels.has(server.subscription_id);
  }

  const subscriptionOptions = $derived.by(() => {
    const options: Option<string>[] = [{ value: ALL, label: 'All subscriptions' }];
    for (const link of subscriptionLinks.list) {
      options.push({ value: link.id, label: subscriptionLinks.label(link.id) });
    }
    if (outboundServers.list.some((server) => !knownSubscription(server))) {
      options.push({ value: OTHER, label: 'Other' });
    }
    return options;
  });

  const protocolOptions = $derived<Option<string>[]>([
    { value: ALL, label: 'All protocols' },
    ...outboundServers.protocols.map((value) => ({ value, label: protocolLabel(value) })),
  ]);

  const sortOptions = (Object.keys(SORT_LABELS) as SortKey[]).map((value) => ({
    value,
    label: `By ${SORT_LABELS[value].toLowerCase()}`,
  }));

  // A filter whose value disappeared (a deleted subscription) falls back to all.
  $effect(() => {
    if (!subscriptionOptions.some((option) => option.value === subscription)) subscription = ALL;
  });
  $effect(() => {
    if (!protocolOptions.some((option) => option.value === protocol)) protocol = ALL;
  });

  function matches(server: OutboundServer): boolean {
    if (
      subscription === OTHER
        ? knownSubscription(server)
        : subscription !== ALL && server.subscription_id !== subscription
    ) {
      return false;
    }
    return protocol === ALL || server.protocol === protocol;
  }

  const filtered = $derived(outboundServers.list.filter(matches));

  // The subscription column fits the longest shown label (about 7px a character
  // plus the tag's swatch and padding), so the tags are not cut.
  const subscriptionWidth = $derived.by(() => {
    let longest = 0;
    for (const id of new Set(filtered.map((server) => server.subscription_id))) {
      longest = Math.max(longest, subscriptionLinks.label(id).length);
    }
    return `${Math.min(160, Math.max(72, longest * 7 + 28))}px`;
  });

  // While servers are being checked, each result would move its row. Rows keep
  // their places until the check ends; changing the sort or filters, including
  // name filters, re-sorts. Filtered servers go last: they cannot be connected.
  let shownIds: string[] = [];
  let shownQuery = '';
  const rows = $derived.by(() => {
    const nameFilters = regFilters.list.map((filter) => filter.id).join(' ');
    const query = [sort, subscription, protocol, nameFilters].join('\n');
    const compare = filteredLast(COMPARATORS[sort]);
    const result =
      tasks.testing && query === shownQuery
        ? keepOrder(shownIds, filtered, compare)
        : [...filtered].sort(compare);
    shownIds = result.map((server) => server.id);
    shownQuery = query;
    return result;
  });

  const filtersActive = $derived(subscription !== ALL || protocol !== ALL);

  function resetFilters() {
    subscription = ALL;
    protocol = ALL;
  }

  async function setAutoConnect(enabled: boolean) {
    autoConnectPending = enabled;
    autoConnectError = null;
    try {
      await serverSettings.setAutoConnect(enabled);
    } catch (reason) {
      autoConnectError = describeError(reason);
    } finally {
      autoConnectPending = null;
    }
  }

  async function checkAll() {
    checkError = null;
    try {
      await tasks.testServers();
    } catch (reason) {
      checkError = describeError(reason, {
        conflict: 'Servers cannot be checked while subscriptions are updating.',
        cancelled: 'The check stopped because subscriptions started updating.',
      });
    }
  }
</script>

<Block
  title="Servers"
  icon="server"
  {order}
  fill
  flush
  meta={loading ? undefined : filtersActive ? `${rows.length} of ${total}` : String(total)}
  hint="Click a server for details. Filtered servers are grayed out at the end of the list and cannot be connected. A check measures ping and speed and runs the tests through every server, one by one; rows keep their places until it ends. With auto-connect on, the router picks the server itself and switches when it fails or gets worse; connecting a server by hand turns auto-connect off."
>
  {#snippet actions()}
    <Switch
      label="Auto-connect"
      shortLabel="Auto"
      checked={autoConnectPending ?? autoConnect}
      busy={autoConnectPending !== null}
      disabled={!connection.ready || loading}
      title={autoConnectPending === true
        ? 'Checking servers to choose one…'
        : autoConnect
          ? 'The router picks the server and switches when it fails or gets worse. Connecting a server by hand turns this off.'
          : 'Let the router pick the best server and switch when it fails or gets worse'}
      onchange={setAutoConnect}
    />
    <Button
      size="sm"
      icon="gauge"
      busy={tasks.testing}
      disabled={!connection.ready || tasks.refreshing || total === 0}
      title={tasks.refreshing
        ? 'Wait until subscriptions are updated'
        : tasks.testing
          ? 'Checking servers one by one. Rows keep their order until the check ends.'
          : 'Check ping, speed and tests of all servers'}
      onclick={checkAll}
    >
      {tasks.testing ? 'Checking…' : 'Check all'}
    </Button>
  {/snippet}

  <div class="toolbar">
    <div class="filters">
      <Select
        size="sm"
        aria-label="Subscription"
        bind:value={subscription}
        options={subscriptionOptions}
      />
      <Select size="sm" aria-label="Protocol" bind:value={protocol} options={protocolOptions} />
      <Select size="sm" aria-label="Sort" bind:value={sort} options={sortOptions} />
    </div>
    {#if autoConnectError}
      <Notice tone="danger" ondismiss={() => (autoConnectError = null)}>{autoConnectError}</Notice>
    {/if}
    {#if checkError}
      <Notice tone="danger" ondismiss={() => (checkError = null)}>{checkError}</Notice>
    {/if}
  </div>

  <div
    class="scroll"
    style:--tests-width={testsWidth}
    style:--subscription-width={subscriptionWidth}
  >
    {#if loading}
      <EmptyState loading title="Loading servers…" />
    {:else if total === 0}
      <EmptyState
        icon="server"
        title="No servers yet"
        hint="Add a subscription link, and its servers will appear here."
      />
    {:else if rows.length === 0}
      <EmptyState icon="search" title="No servers match">
        <Button onclick={resetFilters}>Reset filters</Button>
      </EmptyState>
    {:else}
      <div class="columns" aria-hidden="true">
        <span>Server</span>
        <span>Subscription</span>
        <span>Rating</span>
        <span>Tests</span>
      </div>
      <ul class="list" aria-label="Servers">
        {#each rows as server (server.id)}
          <ServerRow
            {server}
            {tests}
            subscription={subscriptionLinks.label(server.subscription_id)}
            subscriptionColor={subscriptionLinks.color(server.subscription_id)}
            expanded={expanded === server.id}
            ontoggle={() => (expanded = expanded === server.id ? null : server.id)}
            ready={connection.ready}
          />
        {/each}
      </ul>
    {/if}
  </div>
</Block>

<style>
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    padding: 0 var(--space-3) var(--space-2);
  }

  .filters {
    display: flex;
    flex: 1 1 auto;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .filters > :global(*) {
    flex: 1 1 7rem;
  }

  .toolbar > :global(.notice) {
    flex-basis: 100%;
  }

  /* Server, subscription, rating, tests, chevron; see ServerRow. */
  .scroll {
    --server-columns: minmax(7rem, 2fr) minmax(4.5rem, var(--subscription-width)) 5.5rem
      var(--tests-width) 14px;
    --action-width: 92px;
    /* Also clips absolutely positioned descendants (visually hidden labels). */
    position: relative;
    min-height: 0;
  }

  .columns {
    position: sticky;
    top: 0;
    z-index: 1;
    display: grid;
    grid-template-columns: var(--server-columns);
    gap: var(--space-2);
    padding: 2px calc(var(--action-width) + var(--space-3)) 2px var(--space-3);
    background: var(--color-surface);
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
  }

  .list {
    padding-bottom: var(--space-1);
  }

  @container block (width < 500px) {
    .scroll {
      --server-columns: minmax(7rem, 2fr) minmax(4.5rem, var(--subscription-width)) 5.5rem
        var(--tests-width);
    }
  }

  @container block (width < 460px) {
    .columns {
      display: none;
    }
  }

  @media (min-width: 760px) {
    .scroll {
      flex: 1 1 auto;
      overflow-y: auto;
      border-bottom-left-radius: var(--radius-lg);
      border-bottom-right-radius: var(--radius-lg);
    }
  }
</style>
