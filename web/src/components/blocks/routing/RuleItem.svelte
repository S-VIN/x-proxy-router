<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { RoutingRule } from '../../../lib/api/protocol';
  import { actionInfo } from '../../../lib/routing';
  import { routingRules } from '../../../lib/stores';
  import Badge from '../../ui/Badge.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
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
    <span class="move">
      <button
        type="button"
        class="arrow"
        aria-label="Move up: check before the rule above"
        title="Move up"
        disabled={!ready || moving || deleting || rule.priority <= 1}
        onclick={() => move(-1)}
      >
        <Icon name="chevron-up" size={12} />
      </button>
      <button
        type="button"
        class="arrow"
        aria-label="Move down: check after the rule below"
        title="Move down"
        disabled={!ready || moving || deleting || rule.priority >= count}
        onclick={() => move(1)}
      >
        <Icon name="chevron-down" size={12} />
      </button>
    </span>
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

  /* Two small arrows, one above the other, as tall as the row. */
  .move {
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }

  .arrow {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 13px;
    padding: 0;
    border: none;
    border-radius: var(--radius-sm);
    background: none;
    color: var(--color-text-muted);
    transition: background-color var(--duration-fast) var(--easing);
  }

  .arrow:not(:disabled):hover {
    background: var(--color-control-hover);
    color: var(--color-text);
  }

  .arrow:disabled {
    color: var(--color-text-faint);
    opacity: 0.4;
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
