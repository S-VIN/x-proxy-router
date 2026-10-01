<script lang="ts">
  import { actionInfo, catchAllIndex } from '../../lib/routing';
  import { connection, routingRules, serverSettings } from '../../lib/stores';
  import Block from '../layout/Block.svelte';
  import Badge from '../ui/Badge.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import AddRuleForm from './routing/AddRuleForm.svelte';
  import RuleItem from './routing/RuleItem.svelte';

  let { order }: { order: number } = $props();

  // Snapshots of all models come together; settings are the first of them.
  const loading = $derived(serverSettings.current === null);
  const rules = $derived(routingRules.list);
  const catchAll = $derived(catchAllIndex(rules));
  // Traffic no rule matches goes as with proxy; the server does not let it change.
  const rest = actionInfo('proxy');
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
    <ol class="rules">
      {#each rules as rule, index (rule.id)}
        <RuleItem
          {rule}
          count={rules.length}
          shadowed={catchAll >= 0 && index > catchAll}
          ready={connection.ready}
        />
      {/each}
      <li
        class="rest"
        class:shadowed={catchAll >= 0}
        title={catchAll >= 0
          ? 'Never used: the * rule catches all traffic.'
          : 'Traffic no rule matches. This cannot be changed: add a * rule to send it elsewhere.'}
      >
        <span class="text">Everything else</span>
        <Badge tone={rest.tone} title={rest.text}>{rest.label}</Badge>
      </li>
    </ol>
    <AddRuleForm ready={connection.ready} />
  {/if}
</Block>

<style>
  .rules {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  /* Lined up with the rules: the text after their numbers, the badge before their buttons. */
  .rest {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--control-height-sm);
    padding: 0 calc(var(--control-height-sm) + var(--space-2)) 0 calc(1.125rem + var(--space-2));
  }

  .text {
    flex: 1;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    font-style: italic;
  }

  .shadowed {
    opacity: 0.5;
  }
</style>
