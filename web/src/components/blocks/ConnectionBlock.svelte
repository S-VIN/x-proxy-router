<script lang="ts">
  import {
    EMPTY,
    formatPing,
    formatSpeed,
    pingTone,
    ratingTone,
    stackLabel,
  } from '../../lib/format';
  import { outboundServers, serverSettings, subscriptionLinks } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import Stat from '../ui/Stat.svelte';
  import Tag from '../ui/Tag.svelte';

  let { order }: { order: number } = $props();

  const server = $derived(outboundServers.connected);
  const tests = $derived(serverSettings.current?.outbound_tests ?? []);
  const passed = $derived(
    server?.tests ? tests.filter((test) => server?.tests?.[test.alias] === true).length : null,
  );
</script>

<Block
  title="Connection"
  icon="route"
  {order}
  hint="The server your traffic goes through. To switch, press Connect on another server."
>
  {#if serverSettings.current === null}
    <EmptyState compact loading title="Loading…" />
  {:else if server === null}
    <EmptyState
      compact
      icon="plug"
      title="No server selected"
      hint="Pick a server in the list and press Connect to send traffic through it."
    />
  {:else}
    <div class="current">
      <p class="name" title="{server.name}, {server.address}:{server.port}">{server.name}</p>
      <p class="about">
        <Tag color={subscriptionLinks.color(server.subscription_id)}>
          {subscriptionLinks.label(server.subscription_id)}
        </Tag>
        <span class="stack">{stackLabel(server)}</span>
      </p>
    </div>
    <dl class="stats">
      <Stat label="Ping" tone={pingTone(server.ping)}>{formatPing(server.ping)}</Stat>
      <Stat label="Speed" tone={server.speed === 0 ? 'danger' : 'neutral'}>
        {formatSpeed(server.speed)}
      </Stat>
      <Stat label="Rating" tone={ratingTone(server.rating)}>{server.rating ?? EMPTY}</Stat>
      <Stat
        label="Tests"
        tone={passed === null || tests.length === 0
          ? 'neutral'
          : passed === tests.length
            ? 'success'
            : passed === 0
              ? 'danger'
              : 'warning'}
      >
        {passed === null || tests.length === 0 ? EMPTY : `${passed}/${tests.length}`}
      </Stat>
    </dl>
  {/if}
</Block>

<style>
  .current {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .name {
    overflow: hidden;
    font-weight: var(--weight-bold);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .about {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }

  .stack {
    overflow: hidden;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Each value as wide as it needs; two by two when the block is narrow. */
  .stats {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
  }

  @container block (width < 240px) {
    .stats {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-2);
    }
  }
</style>
