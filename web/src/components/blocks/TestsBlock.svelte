<script lang="ts">
  import { untrack } from 'svelte';
  import { describeError } from '../../lib/api/errors';
  import type { OutboundTest } from '../../lib/api/protocol';
  import { hostLabel, ruleLabel } from '../../lib/format';
  import { connection, serverSettings } from '../../lib/stores';
  import { hasErrors, validateTests } from '../../lib/validation';
  import Block from '../layout/Block.svelte';
  import Badge from '../ui/Badge.svelte';
  import Button from '../ui/Button.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import Notice from '../ui/Notice.svelte';
  import TestEditor from './tests/TestEditor.svelte';

  let { order }: { order: number } = $props();

  interface DraftTest extends OutboundTest {
    /** Stable key for the list while names are edited. */
    key: number;
  }

  let nextKey = 0;
  const serverTests = $derived(serverSettings.current?.outbound_tests ?? null);

  // Tests are shown as a list; the editor opens on demand.
  let editing = $state(false);
  // The list being edited and the server list it started from.
  let draft = $state<DraftTest[]>([]);
  let base = $state<OutboundTest[] | null>(null);
  let submitted = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);
  let addedKey = $state<number | null>(null);

  function normalized(tests: readonly OutboundTest[]): OutboundTest[] {
    return tests.map(({ alias, url, rule }) => ({ alias: alias.trim(), url: url.trim(), rule }));
  }

  function same(a: readonly OutboundTest[], b: readonly OutboundTest[]): boolean {
    return JSON.stringify(normalized(a)) === JSON.stringify(normalized(b));
  }

  function reset(tests: readonly OutboundTest[]) {
    base = normalized(tests);
    draft = tests.map((test) => ({ ...test, key: nextKey++ }));
    submitted = false;
    addedKey = null;
  }

  const dirty = $derived(base !== null && !same(draft, base));
  /** Someone else changed the tests while this list has unsaved edits. */
  const outdated = $derived(
    dirty && base !== null && serverTests !== null && !same(base, serverTests),
  );
  const errors = $derived(validateTests(draft));
  const shownErrors = $derived(submitted ? errors : draft.map(() => ({})));

  // Follow the server while there are no local edits, or when it now has exactly them.
  $effect(() => {
    const tests = serverTests;
    if (tests === null) return;
    untrack(() => {
      if (base === null || !dirty || same(tests, draft)) reset(tests);
    });
  });

  function startEditing() {
    if (serverTests) reset(serverTests);
    error = null;
    editing = true;
  }

  function stopEditing() {
    editing = false;
    error = null;
  }

  function add() {
    const key = nextKey++;
    draft.push({ key, alias: '', url: '', rule: 'status_2xx' });
    addedKey = key;
  }

  function remove(key: number) {
    draft = draft.filter((test) => test.key !== key);
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (hasErrors(errors)) return;
    if (!dirty) {
      stopEditing();
      return;
    }
    saving = true;
    error = null;
    try {
      await serverSettings.setOutboundTests(normalized(draft));
      if (serverTests) reset(serverTests);
      editing = false;
    } catch (reason) {
      error = describeError(reason, {
        validation_error: 'The server rejected a test. Check the names and URLs.',
      });
    } finally {
      saving = false;
    }
  }
</script>

<Block
  title="Tests"
  icon="tests"
  {order}
  meta={serverTests ? String(serverTests.length) : undefined}
  hint="Every server check requests these URLs through the server. A test passes when the response status matches its rule; redirects are not followed."
>
  {#snippet actions()}
    {#if serverTests !== null && !editing}
      <Button variant="flat" size="sm" icon="edit" onclick={startEditing}>Edit</Button>
    {/if}
  {/snippet}

  {#if serverTests === null}
    <EmptyState compact loading title="Loading…" />
  {:else if !editing}
    {#if serverTests.length === 0}
      <p class="muted small" title="Servers are rated by ping and speed only.">No tests</p>
    {:else}
      <ul class="tests">
        {#each serverTests as test, index (index)}
          <li class="test" title={`${test.url}\nPasses: ${ruleLabel(test.rule)}`}>
            <span class="alias">{test.alias}</span>
            <span class="url">{hostLabel(test.url)}</span>
            <Badge>{ruleLabel(test.rule)}</Badge>
          </li>
        {/each}
      </ul>
    {/if}
  {:else}
    <form class="form" novalidate onsubmit={save}>
      {#if draft.length === 0}
        <p class="muted small" title="Servers are rated by ping and speed only.">No tests</p>
      {:else}
        <ul class="editors">
          {#each draft as test, index (test.key)}
            <TestEditor
              bind:alias={test.alias}
              bind:url={test.url}
              bind:rule={test.rule}
              errors={shownErrors[index] ?? {}}
              disabled={saving}
              autofocus={test.key === addedKey}
              onremove={() => remove(test.key)}
            />
          {/each}
        </ul>
      {/if}

      <div class="add">
        <Button variant="flat" size="sm" icon="add" disabled={saving} onclick={add}>Add test</Button
        >
      </div>
      {#if outdated}
        <Notice tone="warning">
          {#snippet actions()}
            <Button size="sm" onclick={() => serverTests && reset(serverTests)}>Load theirs</Button>
          {/snippet}
          The tests were changed on the server. Saving replaces that version with yours.
        </Notice>
      {/if}
      {#if error}
        <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
      {/if}

      <div class="footer">
        <Button variant="flat" size="sm" disabled={saving} onclick={stopEditing}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          busy={saving}
          disabled={!connection.ready}
        >
          Save
        </Button>
      </div>
    </form>
  {/if}
</Block>

<style>
  .tests {
    display: flex;
    flex-direction: column;
  }

  /* Name, host and rule on one line; the whole URL is in the tooltip. */
  .test {
    display: grid;
    grid-template-columns: minmax(0, auto) minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-2);
    min-height: 24px;
  }

  .alias {
    max-width: 9rem;
    overflow: hidden;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .url {
    overflow: hidden;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .editors {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .add {
    display: flex;
  }

  .footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }
</style>
