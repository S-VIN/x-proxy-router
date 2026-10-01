<script lang="ts">
  import { describeError, RequestError } from '../../../lib/api/errors';
  import type { TestRule } from '../../../lib/api/protocol';
  import { ruleLabel, TEST_RULES } from '../../../lib/format';
  import { outboundTests } from '../../../lib/stores';
  import { testUrlError } from '../../../lib/validation';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Select from '../../ui/Select.svelte';
  import TextField from '../../ui/TextField.svelte';

  let { ready }: { ready: boolean } = $props();

  const ruleOptions = TEST_RULES.map((value) => ({ value, label: ruleLabel(value) }));

  let url = $state('');
  let rule = $state<TestRule>('status_2xx');
  let submitted = $state(false);
  let adding = $state(false);
  let error = $state<string | null>(null);
  // The server's reason for rejecting the URL, shown until it is edited.
  let rejected = $state<{ url: string; text: string } | null>(null);

  const urlError = $derived(
    (submitted ? testUrlError(url, outboundTests.list) : null) ??
      (rejected?.url === url ? rejected.text : null),
  );

  async function add(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (testUrlError(url, outboundTests.list)) return;
    adding = true;
    error = null;
    rejected = null;
    try {
      await outboundTests.add(url.trim(), rule);
      url = '';
      submitted = false;
    } catch (reason) {
      if (reason instanceof RequestError && reason.field === 'url') {
        rejected = {
          url,
          text:
            reason.code === 'conflict'
              ? 'A test with this URL already exists.'
              : 'Use an http:// or https:// URL with a host.',
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
  <div class="row">
    <TextField
      size="sm"
      type="url"
      inputmode="url"
      placeholder="https://example.com/"
      aria-label="New test: the URL to request"
      bind:value={url}
      invalid={urlError !== null}
      disabled={adding}
    />
    <Select
      size="sm"
      aria-label="The new test passes when the response status is"
      title="Passes when the response status is"
      bind:value={rule}
      options={ruleOptions}
      disabled={adding}
    />
    <Button
      type="submit"
      size="sm"
      variant="primary"
      icon="add"
      label="Add test"
      busy={adding}
      disabled={!ready}
    />
  </div>
  {#if urlError}
    <p class="invalid">{urlError}</p>
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

  /* The URL takes the room the rule and the button leave. */
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
