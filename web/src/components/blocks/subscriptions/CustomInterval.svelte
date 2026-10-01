<script lang="ts">
  import { splitInterval, UNIT_SECONDS, type IntervalUnit } from '../../../lib/format';
  import Button from '../../ui/Button.svelte';
  import Select from '../../ui/Select.svelte';
  import TextField from '../../ui/TextField.svelte';

  interface Props {
    /** The interval the server uses now, in seconds. */
    interval: number;
    saving: boolean;
    ready: boolean;
    onapply: (seconds: number) => void;
  }

  let { interval, saving, ready, onapply }: Props = $props();

  const unitOptions: { value: IntervalUnit; label: string }[] = [
    { value: 'minutes', label: 'minutes' },
    { value: 'hours', label: 'hours' },
    { value: 'days', label: 'days' },
  ];

  // Follow the server; the user's edits override these until the interval changes.
  let value = $derived(String(splitInterval(interval).value));
  let unit = $derived(splitInterval(interval).unit);
  let submitted = $state(false);

  const seconds = $derived.by(() => {
    const number = Number(value.trim());
    return Number.isInteger(number) && number > 0 ? number * UNIT_SECONDS[unit] : null;
  });

  function apply(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    if (seconds !== null) onapply(seconds);
  }
</script>

<form class="custom" novalidate onsubmit={apply}>
  <span class="every">Every</span>
  <TextField
    size="sm"
    inputmode="numeric"
    aria-label="Interval"
    bind:value
    invalid={submitted && seconds === null}
  />
  <Select size="sm" aria-label="Unit" bind:value={unit} options={unitOptions} />
  <Button type="submit" size="sm" busy={saving} disabled={!ready || seconds === interval}>
    Apply
  </Button>
</form>
{#if submitted && seconds === null}
  <p class="invalid">Enter a whole number greater than zero.</p>
{/if}

<style>
  .custom {
    display: grid;
    grid-template-columns: auto minmax(3rem, 1fr) minmax(0, 1.4fr) auto;
    align-items: center;
    gap: var(--space-2);
  }

  .every {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .invalid {
    color: var(--color-danger-text);
    font-size: var(--text-xs);
  }
</style>
