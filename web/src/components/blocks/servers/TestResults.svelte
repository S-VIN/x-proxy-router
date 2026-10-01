<script lang="ts">
  import type { OutboundServer, OutboundTest } from '../../../lib/api/protocol';
  import { EMPTY } from '../../../lib/format';
  import { outboundTests } from '../../../lib/stores';

  interface Props {
    results: OutboundServer['tests'];
    /** The current tests; results of removed tests are not shown. */
    tests: readonly OutboundTest[];
  }

  let { results, tests }: Props = $props();

  const items = $derived(
    tests.map((test) => ({
      id: test.id,
      label: outboundTests.label(test.id),
      passed: results?.[test.id] ?? null,
    })),
  );
  const passed = $derived(items.filter((item) => item.passed === true).length);
  const checked = $derived(items.filter((item) => item.passed !== null).length);
  // One line per test: shown on hover and read by screen readers.
  const summary = $derived(
    [
      `${passed} of ${items.length} tests passed`,
      ...items.map(
        (item) =>
          `${item.label}: ${item.passed === null ? 'not checked' : item.passed ? 'passed' : 'failed'}`,
      ),
    ].join('\n'),
  );
</script>

{#if results === null || tests.length === 0 || checked === 0}
  <span class="none" title={tests.length === 0 ? 'No tests configured' : 'Not checked'}
    >{EMPTY}</span
  >
{:else}
  <!-- A mark per test in the order of the Tests block: filled passed, hollow failed. -->
  <span class="results" role="img" aria-label={summary} title={summary}>
    {#each items as item (item.id)}
      <span class="mark" class:passed={item.passed === true} class:failed={item.passed === false}
      ></span>
    {/each}
  </span>
{/if}

<style>
  .none {
    color: var(--color-text-faint);
  }

  .results {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    height: 100%;
  }

  .mark {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    box-shadow: inset 0 0 0 1.5px var(--color-border-strong);
  }

  .passed {
    background: var(--color-success);
    box-shadow: none;
  }

  .failed {
    box-shadow: inset 0 0 0 2px var(--color-danger);
  }
</style>
