<script lang="ts">
  import { describeError, RequestError } from '../../../lib/api/errors';
  import type { RoutingAction } from '../../../lib/api/protocol';
  import {
    actionInfo,
    normalizedPattern,
    ROUTING_ACTIONS,
    routingPatternError,
  } from '../../../lib/routing';
  import { routingRules } from '../../../lib/stores';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Select from '../../ui/Select.svelte';
  import TextField from '../../ui/TextField.svelte';

  let { ready }: { ready: boolean } = $props();

  const actionOptions = ROUTING_ACTIONS.map((value) => ({
    value,
    label: actionInfo(value).label,
  }));

  let reg = $state('');
  let action = $state<RoutingAction>('direct');
  let submitted = $state(false);
  let adding = $state(false);
  let error = $state<string | null>(null);
  // The server's reason for rejecting a pattern, shown until it is edited.
  let rejected = $state<{ reg: string; text: string } | null>(null);

  const regError = $derived(
    (submitted ? routingPatternError(reg, routingRules.list) : null) ??
      (rejected?.reg === reg ? rejected.text : null),
  );

  async function add(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (routingPatternError(reg, routingRules.list)) return;
    adding = true;
    error = null;
    rejected = null;
    try {
      await routingRules.add(normalizedPattern(reg), action);
      reg = '';
      submitted = false;
    } catch (reason) {
      if (reason instanceof RequestError && reason.field === 'reg') {
        rejected = {
          reg,
          text:
            reason.code === 'conflict' ? 'A rule for this address already exists.' : reason.message,
        };
      } else {
        error = describeError(reason);
      }
    } finally {
      adding = false;
    }
  }
</script>

<form class="form" novalidate onsubmit={add}>
  <TextField
    size="sm"
    class="mono"
    placeholder="e.g. *.youtube.com or 10.*"
    aria-label="New rule: a domain or IP address pattern"
    bind:value={reg}
    invalid={regError !== null}
    disabled={adding}
  />
  {#if regError}
    <p class="invalid">{regError}</p>
  {/if}
  <div class="row">
    <Select
      size="sm"
      aria-label="Where the traffic of the new rule goes"
      bind:value={action}
      options={actionOptions}
      disabled={adding}
    />
    <Button
      type="submit"
      size="sm"
      variant="primary"
      icon="add"
      busy={adding}
      disabled={!ready}
      title="Add the rule; it is checked after the others"
    >
      Add
    </Button>
  </div>
  {#if error}
    <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
  {/if}
</form>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }

  .row {
    display: flex;
    gap: var(--space-2);
  }

  .row > :global(:first-child) {
    flex: 1;
  }

  .invalid {
    color: var(--color-danger-text);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }
</style>
