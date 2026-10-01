<script lang="ts">
  import { untrack } from 'svelte';
  import { describeError, RequestError } from '../../../lib/api/errors';
  import type { InboundServer, InboundType } from '../../../lib/api/protocol';
  import {
    draftErrors,
    draftFields,
    draftSettings,
    INBOUND_TYPES,
    inboundDraft,
    inboundTypeLabel,
    type FieldErrors,
    type InboundDraft,
  } from '../../../lib/inbounds';
  import { inboundServers } from '../../../lib/stores';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import ProxyFields from './ProxyFields.svelte';

  interface Props {
    /** The inbound to edit; null adds a new one, starting with its type. */
    inbound: InboundServer | null;
    ready: boolean;
    /** Called after saving or on cancel. */
    onclose: () => void;
  }

  let { inbound, ready, onclose }: Props = $props();

  // Settings of the chosen type; null while a new inbound has no type yet. They start
  // from the inbound as it is when the form opens and then keep the user's edits.
  let draft = $state<InboundDraft | null>(
    untrack(() => (inbound ? inboundDraft(inbound.type, inbound, inboundServers.list) : null)),
  );
  let submitted = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);
  // The server's reason for rejecting a field, shown until the form is edited.
  let rejected = $state<{ field: string; text: string; draft: string } | null>(null);

  const errors = $derived(draft ? draftErrors(draft, inbound, inboundServers.list) : {});
  const shownErrors = $derived.by((): FieldErrors => {
    const shown = submitted ? { ...errors } : {};
    if (rejected && JSON.stringify(draft) === rejected.draft) {
      shown[rejected.field] ??= rejected.text;
    }
    return shown;
  });

  function choose(type: InboundType) {
    draft = inboundDraft(type, null, inboundServers.list);
    submitted = false;
    error = null;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (draft === null) return;
    submitted = true;
    if (Object.keys(errors).length > 0) return;
    const settings = draftSettings(draft, inbound);
    if (inbound && Object.keys(settings).length === 0) {
      onclose();
      return;
    }
    saving = true;
    error = null;
    rejected = null;
    try {
      if (inbound) await inboundServers.change(inbound.id, settings);
      else await inboundServers.add(draft.type, settings);
      onclose();
    } catch (reason) {
      // A busy port or a missing address: the message names the cause, shown at the field.
      const field = reason instanceof RequestError ? reason.field : undefined;
      if (reason instanceof RequestError && field && draftFields(draft).includes(field)) {
        rejected = { field, text: reason.message, draft: JSON.stringify(draft) };
      } else {
        error = describeError(reason, {
          not_found: 'This inbound was deleted.',
          core_error: 'The proxy core could not start the inbound. See the server log for details.',
        });
      }
    } finally {
      saving = false;
    }
  }
</script>

<form class="form" novalidate onsubmit={save}>
  {#if draft === null}
    <p class="step">Choose a type</p>
    <ul class="types">
      {#each INBOUND_TYPES as info (info.type)}
        <li>
          <button type="button" class="type" onclick={() => choose(info.type)}>
            <span class="type-label">{info.label}</span>
            <span class="type-text">{info.description}</span>
          </button>
        </li>
      {/each}
    </ul>
  {:else}
    {#if inbound === null}
      <div class="chosen">
        <span class="step">{inboundTypeLabel(draft.type)}</span>
        <Button variant="flat" size="sm" disabled={saving} onclick={() => (draft = null)}>
          Change type
        </Button>
      </div>
    {/if}
    {#if draft.type === 'proxy'}
      <ProxyFields
        bind:draft={draft.proxy}
        errors={shownErrors}
        hasPassword={inbound?.proxy_username != null}
        disabled={saving}
      />
    {/if}
  {/if}

  {#if error}
    <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
  {/if}

  <div class="footer">
    <Button variant="flat" size="sm" disabled={saving} onclick={onclose}>Cancel</Button>
    {#if draft !== null}
      <Button type="submit" variant="primary" size="sm" busy={saving} disabled={!ready}>
        {inbound ? 'Save' : 'Add'}
      </Button>
    {/if}
  </div>
</form>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2);
    border-radius: var(--radius-md);
    background: var(--color-surface-sunken);
  }

  .step {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
  }

  .types {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  /* Each type is a card: its name, then what it is for. */
  .type {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
    padding: var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    color: var(--color-text);
    text-align: left;
    transition: background-color var(--duration-fast) var(--easing);
  }

  .type:hover {
    background: var(--color-hover);
  }

  .type-label {
    font-size: var(--text-sm);
    font-weight: var(--weight-bold);
  }

  .type-text {
    color: var(--color-text-muted);
    font-size: var(--text-xs);
  }

  .chosen {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
  }
</style>
