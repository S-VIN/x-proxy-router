<script lang="ts">
  import { describeError, RequestError } from '../../../lib/api/errors';
  import type { InboundServer } from '../../../lib/api/protocol';
  import {
    inboundAddress,
    inboundDetails,
    inboundDraft,
    inboundTypeLabel,
  } from '../../../lib/inbounds';
  import { inboundServers } from '../../../lib/stores';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Switch from '../../ui/Switch.svelte';
  import InboundForm from './InboundForm.svelte';

  let { inbound, ready }: { inbound: InboundServer; ready: boolean } = $props();

  let editing = $state(false);
  let toggling = $state(false);
  let retrying = $state(false);
  let deleting = $state(false);
  let error = $state<string | null>(null);

  const address = $derived(inboundAddress(inbound) ?? inboundTypeLabel(inbound.type));
  // Inbounds of types this page does not know can be switched and deleted, not edited.
  const editable = $derived(inboundDraft(inbound.type, inbound, []) !== null);

  /** A busy port or a missing address is named by the server; other failures are generic. */
  function failure(reason: unknown): string {
    if (reason instanceof RequestError && reason.field?.startsWith(`${inbound.type}_`)) {
      return reason.message;
    }
    return describeError(reason, { not_found: 'This inbound was already deleted.' });
  }

  async function setEnabled(enabled: boolean) {
    toggling = true;
    error = null;
    try {
      await inboundServers.change(inbound.id, { enabled });
    } catch (reason) {
      error = failure(reason);
    } finally {
      toggling = false;
    }
  }

  async function retry() {
    retrying = true;
    error = null;
    try {
      await inboundServers.change(inbound.id);
    } catch (reason) {
      // The same cause is already shown with the Retry button.
      const text = failure(reason);
      if (text !== inbound.error) error = text;
    } finally {
      retrying = false;
    }
  }

  async function remove() {
    deleting = true;
    error = null;
    try {
      await inboundServers.remove(inbound.id);
    } catch (reason) {
      error = failure(reason);
      deleting = false;
    }
  }

  function startEditing() {
    editing = true;
    error = null;
  }
</script>

<li class="item" class:off={!inbound.enabled}>
  <div class="head">
    <div class="line">
      <span class="address num" title={address}>{address}</span>
      <Switch
        label="Listen on {address}"
        hideLabel
        checked={inbound.enabled}
        busy={toggling}
        disabled={!ready || deleting || editing}
        title={inbound.enabled
          ? 'Listening. Turn off to close the port and keep the settings.'
          : 'Off: the port is closed. Turn on to listen again.'}
        onchange={setEnabled}
      />
      {#if !editing}
        <div class="actions">
          {#if editable}
            <Button
              variant="flat"
              size="sm"
              icon="edit"
              label="Edit inbound"
              disabled={!ready || deleting}
              onclick={startEditing}
            />
          {/if}
          <Button
            variant="flat"
            size="sm"
            icon="trash"
            label="Delete inbound"
            busy={deleting}
            disabled={!ready}
            onclick={remove}
          />
        </div>
      {/if}
    </div>
    <p class="details">{inboundDetails(inbound)}</p>
  </div>

  {#if inbound.enabled && inbound.error && !editing}
    <Notice tone="danger">
      {#snippet actions()}
        <Button size="sm" busy={retrying} disabled={!ready} onclick={retry}>Retry</Button>
      {/snippet}
      Not listening: {inbound.error}
    </Notice>
  {/if}

  {#if editing}
    <InboundForm {inbound} type={inbound.type} {ready} onclose={() => (editing = false)} />
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
    gap: var(--space-1);
    min-height: var(--control-height-sm);
  }

  .address {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .details {
    overflow: hidden;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .off .address,
  .off .details {
    opacity: 0.55;
  }

  .actions {
    display: flex;
  }
</style>
