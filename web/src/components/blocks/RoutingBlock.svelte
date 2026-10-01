<script lang="ts">
  import { catchAllIndex } from '../../lib/routing';
  import { connection, routingRules, serverSettings } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import AddRuleForm from './routing/AddRuleForm.svelte';
  import RuleItem from './routing/RuleItem.svelte';

  let { order }: { order: number } = $props();

  // Snapshots of all models come together; settings are the first of them.
  const loading = $derived(serverSettings.current === null);
  const rules = $derived(routingRules.list);
  const catchAll = $derived(catchAllIndex(rules));
</script>

<Block
  title="Routing"
  icon="split"
  {order}
  meta={loading ? undefined : String(rules.length)}
  hint="Where the traffic of the inbounds goes. Rules are checked from the top and the first matching one wins; traffic no rule matches goes through the connected server. A rule matches the domain or the IP address an app connects to, ignoring case; * stands for any characters: *.youtube.com, 192.168.*. Domains are not resolved for the rules. Server checks ignore them."
>
  {#if loading}
    <EmptyState compact loading title="Loading…" />
  {:else}
    {#if rules.length === 0}
      <p class="muted small" title="All traffic goes through the connected server.">No rules</p>
    {:else}
      <ol class="rules">
        {#each rules as rule, index (rule.id)}
          <RuleItem
            {rule}
            count={rules.length}
            shadowed={catchAll >= 0 && index > catchAll}
            ready={connection.ready}
          />
        {/each}
      </ol>
    {/if}
    <AddRuleForm ready={connection.ready} />
  {/if}
</Block>

<style>
  .rules {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
