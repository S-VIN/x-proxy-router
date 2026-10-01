<script lang="ts">
  import { untrack } from 'svelte';
  import { describeError, RequestError } from '../../../lib/api/errors';
  import type { InboundServer, InboundType } from '../../../lib/api/protocol';
  import {
    draftErrors,
    draftFields,
    draftSettings,
    inboundDraft,
    inboundTypeLabel,
    type FieldErrors,
  } from '../../../lib/inbounds';
  import { inboundServers } from '../../../lib/stores';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import ProxyFields from './ProxyFields.svelte';

  interface Props {
    /** The inbound to edit; null adds a new one of `type`. */
    inbound: InboundServer | null;
    /** The type of a new inbound; an edited one keeps its own. */
    type: InboundType;
    ready: boolean;
    /** Called after saving or on cancel. */
    onclose: () => void;
  }

  let { inbound, type, ready, onclose }: Props = $props();

  // Settings of the type, null for types this page does not know. They start from
  // the inbound as it is when the form opens and then keep the user's edits.
  let draft = $state(untrack(() => inboundDraft(type, inbound, inboundServers.list)));
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
  {#if inbound === null}
    <p class="title">New {inboundTypeLabel(type).toLowerCase()}</p>
  {/if}
  {#if draft?.type === 'proxy'}
    <ProxyFields
      bind:draft={draft.proxy}
      errors={shownErrors}
      hasPassword={inbound?.proxy_username != null}
      disabled={saving}
    />
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

  .title {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
  }

  .footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
  }
</style>
