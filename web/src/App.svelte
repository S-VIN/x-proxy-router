<script lang="ts">
  import ConnectionBlock from './components/blocks/ConnectionBlock.svelte';
  import FiltersBlock from './components/blocks/FiltersBlock.svelte';
  import InboundsBlock from './components/blocks/InboundsBlock.svelte';
  import RoutingBlock from './components/blocks/RoutingBlock.svelte';
  import ServersBlock from './components/blocks/ServersBlock.svelte';
  import SubscriptionsBlock from './components/blocks/SubscriptionsBlock.svelte';
  import TestsBlock from './components/blocks/TestsBlock.svelte';
  import AppHeader from './components/layout/AppHeader.svelte';
  import ConnectionBanner from './components/layout/ConnectionBanner.svelte';
  import Dashboard from './components/layout/Dashboard.svelte';
  import { logoUrl } from './lib/logo';
  import { linkStatus } from './lib/stores';

  // The tab icon shows the connection state, like the logo in the header.
  $effect(() => {
    const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (icon) icon.href = logoUrl(linkStatus.state);
  });
</script>

<div class="app">
  <AppHeader />
  <ConnectionBanner />
  <!-- order: position of each block when all of them share one column. -->
  <Dashboard>
    {#snippet left()}
      <SubscriptionsBlock order={4} />
      <FiltersBlock order={5} />
    {/snippet}
    {#snippet center()}
      <ServersBlock order={3} />
    {/snippet}
    {#snippet right()}
      <ConnectionBlock order={1} />
      <InboundsBlock order={2} />
      <RoutingBlock order={6} />
      <TestsBlock order={7} />
    {/snippet}
  </Dashboard>
</div>

<style>
  .app {
    display: flex;
    flex-direction: column;
    min-height: 100dvh;
  }

  /* From two columns up the page does not scroll; the columns do. */
  @media (min-width: 760px) {
    .app {
      height: 100dvh;
    }
  }
</style>
