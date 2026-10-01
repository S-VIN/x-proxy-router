<script lang="ts">
  import { describeError, RequestError } from '../../../lib/api/errors';
  import { regFilters } from '../../../lib/stores';
  import { regFilterError } from '../../../lib/validation';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import TextField from '../../ui/TextField.svelte';

  let { ready }: { ready: boolean } = $props();

  let reg = $state('');
  let submitted = $state(false);
  let adding = $state(false);
  let error = $state<string | null>(null);
  // The server's reason for rejecting a pattern, shown until it is edited.
  let rejected = $state<{ reg: string; text: string } | null>(null);

  const regError = $derived(
    (submitted ? regFilterError(reg, regFilters.list) : null) ??
      (rejected?.reg === reg ? rejected.text : null),
  );

  async function add(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (regFilterError(reg, regFilters.list)) return;
    adding = true;
    error = null;
    rejected = null;
    try {
      await regFilters.add(reg);
      reg = '';
      submitted = false;
    } catch (reason) {
      if (reason instanceof RequestError && reason.code === 'validation_error') {
        rejected = { reg, text: reason.message };
      } else {
        error = describeError(reason, { conflict: 'This filter is already added.' });
      }
    } finally {
      adding = false;
    }
  }
</script>

<form class="form" novalidate onsubmit={add}>
  <div class="row">
    <TextField
      size="sm"
      class="mono"
      placeholder="Pattern, e.g. *RU*"
      aria-label="New filter: a pattern for server names"
      bind:value={reg}
      invalid={regError !== null}
      disabled={adding}
    />
    <Button
      type="submit"
      size="sm"
      variant="primary"
      icon="add"
      label="Filter servers whose names match"
      busy={adding}
      disabled={!ready}
    />
  </div>
  {#if regError}
    <p class="invalid">{regError}</p>
  {/if}
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
    min-width: 0;
  }

  .invalid {
    color: var(--color-danger-text);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }
</style>
