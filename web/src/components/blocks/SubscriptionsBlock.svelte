<script lang="ts">
  import { describeError, RequestError } from '../../lib/api/errors';
  import {
    connection,
    outboundServers,
    serverSettings,
    subscriptionLinks,
    tasks,
  } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import Button from '../ui/Button.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import Notice from '../ui/Notice.svelte';
  import AddSubscriptionForm from './subscriptions/AddSubscriptionForm.svelte';
  import CustomInterval from './subscriptions/CustomInterval.svelte';
  import IntervalSelect, { CUSTOM, intervalChoice } from './subscriptions/IntervalSelect.svelte';
  import SubscriptionItem from './subscriptions/SubscriptionItem.svelte';

  let { order }: { order: number } = $props();

  const settings = $derived(serverSettings.current);
  let refreshError = $state<string | null>(null);

  // The interval is chosen in the header; a custom one is entered in the body.
  const interval = $derived(settings?.subscription_refresh_interval ?? null);
  // Follows the server; the user's choice overrides it until the interval changes.
  let choice = $derived(interval === null ? CUSTOM : intervalChoice(interval));
  let saving = $state(false);
  let intervalError = $state<string | null>(null);

  async function setInterval(seconds: number) {
    saving = true;
    intervalError = null;
    try {
      await serverSettings.setRefreshInterval(seconds);
    } catch (reason) {
      intervalError = describeError(reason);
    } finally {
      saving = false;
    }
  }

  async function refresh() {
    refreshError = null;
    try {
      await tasks.refreshSubscriptions();
    } catch (reason) {
      if (reason instanceof RequestError && reason.code === 'subscription_error') {
        const failed = reason.details.failed_id;
        const name =
          typeof failed === 'string' ? subscriptionLinks.label(failed) : 'A subscription';
        refreshError = `${name} failed to load. Servers were left unchanged.`;
      } else {
        refreshError = describeError(reason, { cancelled: 'The update was stopped.' });
      }
    }
  }
</script>

<Block
  title="Subscriptions"
  icon="link"
  {order}
  meta={settings ? String(subscriptionLinks.list.length) : undefined}
  hint="Servers come from these links. Every update reloads servers of all subscriptions. The server keeps links secret and shows only their hosts."
>
  {#snippet actions()}
    {#if interval !== null}
      <IntervalSelect
        bind:value={choice}
        {interval}
        disabled={!connection.ready || saving}
        onpreset={setInterval}
      />
    {/if}
    <Button
      variant="flat"
      size="sm"
      icon="refresh"
      label={tasks.refreshing ? 'Updating subscriptions…' : 'Update subscriptions now'}
      busy={tasks.refreshing}
      disabled={!connection.ready}
      onclick={refresh}
    />
  {/snippet}

  {#if settings === null}
    <EmptyState compact loading title="Loading…" />
  {:else}
    {#if choice === CUSTOM && interval !== null}
      <CustomInterval {interval} {saving} ready={connection.ready} onapply={setInterval} />
    {/if}
    {#if intervalError}
      <Notice tone="danger" ondismiss={() => (intervalError = null)}>{intervalError}</Notice>
    {/if}
    {#if refreshError}
      <Notice tone="danger" ondismiss={() => (refreshError = null)}>{refreshError}</Notice>
    {/if}
    {#if subscriptionLinks.list.length === 0}
      <p class="muted small" title="Add a link from your provider to load its servers.">
        No subscriptions yet
      </p>
    {:else}
      <ul class="list">
        {#each subscriptionLinks.list as link (link.id)}
          <SubscriptionItem
            {link}
            label={subscriptionLinks.label(link.id)}
            color={subscriptionLinks.color(link.id)}
            servers={outboundServers.countBySubscription.get(link.id) ?? 0}
            ready={connection.ready}
          />
        {/each}
      </ul>
    {/if}
    <AddSubscriptionForm ready={connection.ready} />
  {/if}
</Block>

<style>
  .list {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
