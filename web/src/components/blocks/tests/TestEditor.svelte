<script lang="ts">
  import type { TestRule } from '../../../lib/api/protocol';
  import { ruleLabel, TEST_RULES } from '../../../lib/format';
  import type { TestErrors } from '../../../lib/validation';
  import Button from '../../ui/Button.svelte';
  import Select from '../../ui/Select.svelte';
  import TextField from '../../ui/TextField.svelte';

  interface Props {
    alias: string;
    url: string;
    rule: TestRule;
    /** Shown only after the user tried to save. */
    errors: TestErrors;
    disabled: boolean;
    onremove: () => void;
    autofocus?: boolean;
  }

  let {
    alias = $bindable(),
    url = $bindable(),
    rule = $bindable(),
    errors,
    disabled,
    onremove,
    autofocus = false,
  }: Props = $props();

  // A rule from a newer server is kept and shown as is.
  const rules = $derived(TEST_RULES.includes(rule) ? TEST_RULES : [...TEST_RULES, rule]);
  const ruleOptions = $derived(rules.map((value) => ({ value, label: ruleLabel(value) })));
  const message = $derived(errors.alias ?? errors.url);
</script>

<li class="test">
  <TextField
    size="sm"
    placeholder="Name"
    aria-label="Test name"
    bind:value={alias}
    invalid={errors.alias !== undefined}
    {disabled}
    {autofocus}
  />
  <div class="rule">
    <Select
      size="sm"
      aria-label="Passes when the response status is"
      title="Passes when the response status is"
      bind:value={rule}
      options={ruleOptions}
      {disabled}
    />
  </div>
  <div class="url">
    <TextField
      size="sm"
      type="url"
      inputmode="url"
      placeholder="https://example.com/generate_204"
      aria-label="URL to request"
      bind:value={url}
      invalid={errors.url !== undefined}
      {disabled}
    />
  </div>
  <Button variant="flat" size="sm" icon="trash" label="Remove test" {disabled} onclick={onremove} />
  {#if message}
    <p class="invalid">{message}</p>
  {/if}
</li>

<style>
  /* Name and rule on the first line, URL and remove on the second. */
  .test {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-1);
    border-radius: var(--radius-md);
    background: var(--color-surface-sunken);
  }

  .rule,
  .url {
    grid-column: span 2;
    min-width: 0;
  }

  .invalid {
    grid-column: 1 / -1;
    color: var(--color-danger-text);
    font-size: var(--text-xs);
  }
</style>
