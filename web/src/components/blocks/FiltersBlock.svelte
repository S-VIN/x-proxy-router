<script lang="ts">
  import { plural } from '../../lib/format';
  import { connection, outboundServers, regFilters, serverSettings } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import AddFilterForm from './filters/AddFilterForm.svelte';
  import FilterItem from './filters/FilterItem.svelte';

  let { order }: { order: number } = $props();

  // Snapshots of all models come together; settings are the first of them.
  const loading = $derived(serverSettings.current === null);
  const total = $derived(outboundServers.list.length);
</script>

<Block
  title="Name filters"
  icon="filter"
  {order}
  meta={loading ? undefined : String(regFilters.list.length)}
  hint="Servers whose names match any of these patterns are filtered: grayed out at the end of the server list, they cannot be connected and are not checked. A pattern matches the whole name, ignoring case; * stands for any characters: *RU* finds RU anywhere in the name, RU* only at its start."
>
  {#if loading}
    <EmptyState compact loading title="Loading…" />
  {:else}
    {#if regFilters.list.length === 0}
      <p class="muted small" title="Add a pattern to filter servers by name.">No filters</p>
    {:else}
      <ul class="list">
        {#each regFilters.list as filter (filter.id)}
          <FilterItem {filter} ready={connection.ready} />
        {/each}
      </ul>
      {#if total > 0}
        <p class="muted small num">
          {outboundServers.filteredByName} of {plural(total, 'server')} filtered
        </p>
      {/if}
    {/if}
    <AddFilterForm ready={connection.ready} />
  {/if}
</Block>

<style>
  .list {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
