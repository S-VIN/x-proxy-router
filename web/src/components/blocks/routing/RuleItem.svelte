<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { RoutingRule } from '../../../lib/api/protocol';
  import { actionInfo } from '../../../lib/routing';
  import { routingRules } from '../../../lib/stores';
  import Badge from '../../ui/Badge.svelte';
  import Button from '../../ui/Button.svelte';
  import MoveArrows from '../../ui/MoveArrows.svelte';
  import Notice from '../../ui/Notice.svelte';

  interface Props {
    rule: RoutingRule;
    /** Number of rules, the last priority it can move to. */
    count: number;
    /** A rule for every address above catches all traffic, so this one never matches. */
    shadowed: boolean;
    ready: boolean;
  }

  let { rule, count, shadowed, ready }: Props = $props();

  let moving = $state(false);
  let deleting = $state(false);
  let error = $state<string | null>(null);

  const info = $derived(actionInfo(rule.action));

  /** Swaps the rule with its neighbour: the server shifts the rules in between. */
  async function move(step: -1 | 1) {
    moving = true;
    error = null;
    try {
      await routingRules.move(rule.id, rule.priority + step);
    } catch (reason) {
      error = describeError(reason, {
        not_found: 'This rule was deleted.',
        validation_error: 'The rules changed meanwhile. Try again.',
      });
    } finally {
      moving = false;
    }
  }

  async function remove() {
    deleting = true;
    error = null;
    try {
      await routingRules.remove(rule.id);
    } catch (reason) {
      error = describeError(reason, { not_found: 'This rule was already deleted.' });
      deleting = false;
    }
  }
</script>

<li class="item">
  <div class="line">
    <!-- Rules are checked from the top; the arrows move this one. -->
    <MoveArrows
      upLabel="Move up: check before the rule above"
      downLabel="Move down: check after the rule below"
      first={rule.priority <= 1}
      last={rule.priority >= count}
      disabled={!ready || moving || deleting}
      onmove={move}
    />
    <span
      class="rule"
      class:shadowed
      title={shadowed ? 'Never matches: the * rule above catches all traffic.' : undefined}
    >
      <code class="reg" title={rule.reg}>{rule.reg}</code>
      <Badge tone={info.tone} title={info.text}>{info.label}</Badge>
    </span>
    <Button
      variant="flat"
      size="sm"
      icon="trash"
      label="Delete rule"
      busy={deleting}
      disabled={!ready || moving}
      onclick={remove}
    />
  </div>

  {#if error}
    <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
  {/if}
</li>

<style>
  .item {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .line {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--control-height-sm);
  }

  .rule {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }

  .reg {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .shadowed {
    opacity: 0.5;
  }
</style>
