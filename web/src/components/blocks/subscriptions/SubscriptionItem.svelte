<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { SubscriptionLink } from '../../../lib/api/protocol';
  import { plural } from '../../../lib/format';
  import { subscriptionLinks } from '../../../lib/stores';
  import { httpUrlError } from '../../../lib/validation';
  import Button from '../../ui/Button.svelte';
  import ConfirmButton from '../../ui/ConfirmButton.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Tag from '../../ui/Tag.svelte';
  import TextField from '../../ui/TextField.svelte';

  interface Props {
    link: SubscriptionLink;
    label: string;
    /** Tag color, the same as on its servers. */
    color: number | null;
    /** Number of servers loaded from this link. */
    servers: number;
    ready: boolean;
  }

  let { link, label, color, servers, ready }: Props = $props();

  let editing = $state(false);
  let url = $state('');
  let submitted = $state(false);
  let saving = $state(false);
  let deleting = $state(false);
  let error = $state<string | null>(null);

  const urlError = $derived(submitted ? httpUrlError(url) : null);

  function startEditing() {
    editing = true;
    url = '';
    submitted = false;
    error = null;
  }

  function cancel() {
    editing = false;
    url = '';
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (httpUrlError(url)) return;
    saving = true;
    error = null;
    try {
      await subscriptionLinks.change(link.id, url.trim());
      editing = false;
      url = '';
    } catch (reason) {
      error = describeError(reason, {
        conflict: 'Another subscription already uses this link.',
        validation_error: 'Use an http:// or https:// link with a host.',
        not_found: 'This subscription was deleted.',
      });
    } finally {
      saving = false;
    }
  }

  async function remove() {
    deleting = true;
    error = null;
    try {
      await subscriptionLinks.remove(link.id);
    } catch (reason) {
      error = describeError(reason, { not_found: 'This subscription was already deleted.' });
      deleting = false;
    }
  }
</script>

<li class="item">
  <div class="line">
    <span class="name"><Tag {color} title={link.url_short}>{label}</Tag></span>
    <span class="count num">{plural(servers, 'server')}</span>
    {#if !editing}
      <div class="actions">
        <Button
          variant="flat"
          size="sm"
          icon="edit"
          label="Replace link"
          disabled={!ready || deleting}
          onclick={startEditing}
        />
        <ConfirmButton
          label="Delete subscription"
          icon="trash"
          confirmLabel="Delete"
          busy={deleting}
          disabled={!ready}
          onconfirm={remove}
        />
      </div>
    {/if}
  </div>

  {#if editing}
    <form class="edit" novalidate onsubmit={save}>
      <TextField
        size="sm"
        type="url"
        inputmode="url"
        placeholder="Paste the whole new link"
        aria-label="New link for {label}"
        title="The server keeps the current link secret, so enter the whole new one. Its servers load on the next update."
        bind:value={url}
        invalid={urlError !== null}
        disabled={saving}
        autofocus
      />
      {#if urlError}
        <p class="invalid">{urlError}</p>
      {/if}
      <div class="buttons">
        <Button variant="flat" size="sm" onclick={cancel} disabled={saving}>Cancel</Button>
        <Button type="submit" variant="primary" size="sm" busy={saving} disabled={!ready}
          >Save</Button
        >
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

  .name {
    display: flex;
    min-width: 0;
  }

  .count {
    margin-left: auto;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    white-space: nowrap;
  }

  .actions {
    display: flex;
  }

  .edit {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .invalid {
    color: var(--color-danger-text);
    font-size: var(--text-xs);
  }

  .buttons {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
  }
</style>
