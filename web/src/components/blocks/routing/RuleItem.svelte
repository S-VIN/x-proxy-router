<script lang="ts">
  import { describeError, RequestError } from '../../../lib/api/errors';
  import type { RoutingAction, RoutingRule } from '../../../lib/api/protocol';
  import {
    actionInfo,
    normalizedPattern,
    ROUTING_ACTIONS,
    routingPatternError,
  } from '../../../lib/routing';
  import { routingRules } from '../../../lib/stores';
  import Badge from '../../ui/Badge.svelte';
  import Button from '../../ui/Button.svelte';
  import ConfirmButton from '../../ui/ConfirmButton.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Select from '../../ui/Select.svelte';
  import TextField from '../../ui/TextField.svelte';

  interface Props {
    rule: RoutingRule;
    /** Number of rules, the last priority it can move to. */
    count: number;
    /** A rule for every address above catches all traffic, so this one never matches. */
    shadowed: boolean;
    ready: boolean;
  }

  let { rule, count, shadowed, ready }: Props = $props();

  let editing = $state(false);
  let reg = $state('');
  let action = $state<RoutingAction>('direct');
  let priority = $state('1');
  // Values when editing started: only fields changed here are sent, so changes
  // by others in the meantime are kept.
  let start = { reg: '', action: '', priority: 0 };
  let submitted = $state(false);
  let saving = $state(false);
  let deleting = $state(false);
  let error = $state<string | null>(null);
  let rejected = $state<{ reg: string; text: string } | null>(null);

  const info = $derived(actionInfo(rule.action));
  // An action of a newer server is kept and shown as is.
  const actionOptions = $derived(
    (ROUTING_ACTIONS.includes(action) ? ROUTING_ACTIONS : [...ROUTING_ACTIONS, action]).map(
      (value) => ({ value, label: actionInfo(value).label }),
    ),
  );
  const priorityOptions = $derived(
    Array.from({ length: Math.max(count, Number(priority)) }, (_, index) => ({
      value: String(index + 1),
      label: `Priority ${index + 1}`,
    })),
  );
  const regError = $derived(
    (submitted ? routingPatternError(reg, routingRules.list, rule.id) : null) ??
      (rejected?.reg === reg ? rejected.text : null),
  );

  function startEditing() {
    start = { reg: rule.reg, action: rule.action, priority: rule.priority };
    reg = rule.reg;
    action = rule.action;
    priority = String(rule.priority);
    submitted = false;
    rejected = null;
    error = null;
    editing = true;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (routingPatternError(reg, routingRules.list, rule.id)) return;
    const changes: { reg?: string; action?: RoutingAction; priority?: number } = {};
    const pattern = normalizedPattern(reg);
    if (pattern !== start.reg) changes.reg = pattern;
    if (action !== start.action) changes.action = action;
    if (Number(priority) !== start.priority) changes.priority = Number(priority);
    if (Object.keys(changes).length === 0) {
      editing = false;
      return;
    }
    saving = true;
    error = null;
    rejected = null;
    try {
      await routingRules.change(rule.id, changes);
      editing = false;
    } catch (reason) {
      if (reason instanceof RequestError && reason.field === 'reg') {
        rejected = {
          reg,
          text:
            reason.code === 'conflict' ? 'A rule for this address already exists.' : reason.message,
        };
      } else {
        error = describeError(reason, {
          not_found: 'This rule was deleted.',
          validation_error: 'The rules changed meanwhile. Check the priority.',
        });
      }
    } finally {
      saving = false;
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
  <div
    class="line"
    class:shadowed
    title={shadowed ? 'Never matches: the * rule above catches all traffic.' : undefined}
  >
    <span class="priority num">{rule.priority}</span>
    <code class="reg" title={rule.reg}>{rule.reg}</code>
    <Badge tone={info.tone} title={info.text}>{info.label}</Badge>
    {#if !editing}
      <Button
        variant="flat"
        size="sm"
        icon="edit"
        label="Edit rule"
        disabled={!ready}
        onclick={startEditing}
      />
    {/if}
  </div>

  {#if editing}
    <form class="edit" novalidate onsubmit={save}>
      <TextField
        size="sm"
        class="mono"
        aria-label="Domain or IP address"
        bind:value={reg}
        invalid={regError !== null}
        disabled={saving || deleting}
        autofocus
      />
      {#if regError}
        <p class="invalid">{regError}</p>
      {/if}
      <div class="row">
        <Select
          size="sm"
          aria-label="Where the traffic goes"
          bind:value={action}
          options={actionOptions}
          disabled={saving || deleting}
        />
        <Select
          size="sm"
          aria-label="Priority"
          title="Rules are checked by priority, 1 first"
          bind:value={priority}
          options={priorityOptions}
          disabled={saving || deleting}
        />
      </div>
      <div class="buttons">
        <ConfirmButton
          label="Delete rule"
          icon="trash"
          confirmLabel="Delete"
          busy={deleting}
          disabled={!ready || saving}
          onconfirm={remove}
        />
        <span class="spacer"></span>
        <Button variant="flat" size="sm" disabled={saving} onclick={() => (editing = false)}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          busy={saving}
          disabled={!ready || deleting}
        >
          Save
        </Button>
      </div>
    </form>
  {/if}

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

  /* As wide as two digits; the row of the rest in RoutingBlock lines up with it. */
  .priority {
    flex-shrink: 0;
    min-width: 1.125rem;
    color: var(--color-text-faint);
    font-size: var(--text-xs);
    text-align: right;
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

  .edit {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2);
    border-radius: var(--radius-md);
    background: var(--color-surface-sunken);
  }

  .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--space-2);
  }

  .invalid {
    color: var(--color-danger-text);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }

  .buttons {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .spacer {
    flex: 1;
  }
</style>
