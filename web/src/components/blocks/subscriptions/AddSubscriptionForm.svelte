<script lang="ts">
  import { describeError, RequestError } from '../../../lib/api/errors';
  import { subscriptionLinks } from '../../../lib/stores';
  import { httpUrlError } from '../../../lib/validation';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import TextField from '../../ui/TextField.svelte';

  let { ready }: { ready: boolean } = $props();

  let url = $state('');
  let submitted = $state(false);
  let adding = $state(false);
  let result = $state<{ tone: 'info' | 'warning' | 'danger'; text: string } | null>(null);

  const urlError = $derived(submitted ? httpUrlError(url) : null);

  async function add(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (httpUrlError(url)) return;
    adding = true;
    result = null;
    try {
      await subscriptionLinks.add(url.trim());
      url = '';
      submitted = false;
    } catch (reason) {
      // With these errors the link is saved anyway, so the field is cleared.
      if (reason instanceof RequestError && reason.code === 'subscription_error') {
        const failed = reason.details.failed_id;
        const name =
          typeof failed === 'string' ? subscriptionLinks.label(failed) : 'A subscription';
        result = {
          tone: 'warning',
          text: `The link was added, but ${name} failed to load. Servers were left unchanged.`,
        };
        url = '';
        submitted = false;
      } else if (reason instanceof RequestError && reason.code === 'cancelled') {
        result = {
          tone: 'warning',
          text: 'The link was added, but loading its servers was stopped.',
        };
        url = '';
        submitted = false;
      } else {
        result = {
          tone: 'danger',
          text: describeError(reason, {
            conflict: 'This link is already added.',
            validation_error: 'Use an http:// or https:// link with a host.',
          }),
        };
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
      type="url"
      inputmode="url"
      placeholder="Add a subscription link"
      aria-label="New subscription link"
      bind:value={url}
      invalid={urlError !== null}
      disabled={adding}
    />
    <Button
      type="submit"
      size="sm"
      variant="primary"
      icon="add"
      busy={adding}
      disabled={!ready}
      title="Add the link and reload servers of all subscriptions"
    >
      Add
    </Button>
  </div>
  {#if urlError}
    <p class="invalid">{urlError}</p>
  {/if}
  {#if result}
    <Notice tone={result.tone} ondismiss={() => (result = null)}>{result.text}</Notice>
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
  }
</style>
