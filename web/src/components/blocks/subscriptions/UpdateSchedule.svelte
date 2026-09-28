<script lang="ts">
  import { describeError } from '../../../lib/api/errors';
  import type { ServerSettings } from '../../../lib/api/protocol';
  import {
    formatDateTime,
    formatInterval,
    formatRelative,
    splitInterval,
    UNIT_SECONDS,
    type IntervalUnit,
  } from '../../../lib/format';
  import { clock } from '../../../lib/stores/clock.svelte';
  import { connection, serverSettings } from '../../../lib/stores';
  import Button from '../../ui/Button.svelte';
  import Notice from '../../ui/Notice.svelte';
  import Select from '../../ui/Select.svelte';
  import TextField from '../../ui/TextField.svelte';

  let { settings }: { settings: ServerSettings } = $props();

  const CUSTOM = 'custom';
  const PRESETS = [3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400, 7 * 86400];
  const intervalOptions = [
    ...PRESETS.map((seconds) => ({
      value: String(seconds),
      label: capitalize(formatInterval(seconds)),
    })),
    { value: CUSTOM, label: 'Custom…' },
  ];
  const unitOptions: { value: IntervalUnit; label: string }[] = [
    { value: 'minutes', label: 'minutes' },
    { value: 'hours', label: 'hours' },
    { value: 'days', label: 'days' },
  ];

  function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  const interval = $derived(settings.subscription_refresh_interval);
  const lastRefresh = $derived(settings.last_subscription_refresh);

  // Follow the server; the user's choice overrides these until the interval changes.
  let choice = $derived(PRESETS.includes(interval) ? String(interval) : CUSTOM);
  let customValue = $derived(String(splitInterval(interval).value));
  let customUnit = $derived(splitInterval(interval).unit);
  let customSubmitted = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);

  const customSeconds = $derived.by(() => {
    const value = Number(customValue.trim());
    return Number.isInteger(value) && value > 0 ? value * UNIT_SECONDS[customUnit] : null;
  });

  async function apply(seconds: number) {
    saving = true;
    error = null;
    try {
      await serverSettings.setRefreshInterval(seconds);
    } catch (reason) {
      error = describeError(reason);
    } finally {
      saving = false;
    }
  }

  function choose(event: Event) {
    const value = (event.currentTarget as HTMLSelectElement).value;
    choice = value;
    customSubmitted = false;
    if (value !== CUSTOM) void apply(Number(value));
  }

  function applyCustom(event: SubmitEvent) {
    event.preventDefault();
    customSubmitted = true;
    if (customSeconds !== null) void apply(customSeconds);
  }
</script>

<div class="schedule">
  <span
    class="last"
    title={lastRefresh ? `Last update: ${formatDateTime(lastRefresh)}` : undefined}
  >
    {lastRefresh ? `Updated ${formatRelative(lastRefresh, clock.now)}` : 'Never updated'}
  </span>
  <Select
    size="sm"
    aria-label="Update automatically"
    title="Update automatically"
    value={choice}
    options={intervalOptions}
    disabled={!connection.ready || saving}
    onchange={choose}
  />
</div>

{#if choice === CUSTOM}
  <form class="custom" novalidate onsubmit={applyCustom}>
    <span class="every">Every</span>
    <TextField
      size="sm"
      inputmode="numeric"
      aria-label="Interval"
      bind:value={customValue}
      invalid={customSubmitted && customSeconds === null}
    />
    <Select size="sm" aria-label="Unit" bind:value={customUnit} options={unitOptions} />
    <Button
      type="submit"
      size="sm"
      busy={saving}
      disabled={!connection.ready || customSeconds === interval}
    >
      Apply
    </Button>
  </form>
  {#if customSubmitted && customSeconds === null}
    <p class="invalid">Enter a whole number greater than zero.</p>
  {/if}
{/if}

{#if error}
  <Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>
{/if}

<style>
  .schedule {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .last {
    flex-shrink: 0;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    white-space: nowrap;
  }

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
