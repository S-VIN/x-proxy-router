<script lang="ts" module>
  /** The choice that shows CustomInterval. */
  export const CUSTOM = 'custom';

  // Short labels: the select sits in the block header.
  const PRESETS: [number, string][] = [
    [3600, 'Hourly'],
    [3 * 3600, 'Every 3 h'],
    [6 * 3600, 'Every 6 h'],
    [12 * 3600, 'Every 12 h'],
    [86400, 'Daily'],
    [7 * 86400, 'Weekly'],
  ];

  /** The option of the interval: a preset, or CUSTOM. */
  export function intervalChoice(seconds: number): string {
    return PRESETS.some(([preset]) => preset === seconds) ? String(seconds) : CUSTOM;
  }
</script>

<script lang="ts">
  import { formatInterval } from '../../../lib/format';
  import Select from '../../ui/Select.svelte';

  interface Props {
    /** A preset in seconds as a string, or CUSTOM. */
    value: string;
    /** The interval the server uses now. */
    interval: number;
    disabled: boolean;
    /** Called with the seconds of a chosen preset; choosing CUSTOM only changes `value`. */
    onpreset: (seconds: number) => void;
  }

  let { value = $bindable(), interval, disabled, onpreset }: Props = $props();

  const options = [
    ...PRESETS.map(([seconds, label]) => ({ value: String(seconds), label })),
    { value: CUSTOM, label: 'Custom…' },
  ];

  function choose(event: Event) {
    value = (event.currentTarget as HTMLSelectElement).value;
    if (value !== CUSTOM) onpreset(Number(value));
  }
</script>

<Select
  size="sm"
  inline
  aria-label="Update automatically"
  title="Update automatically {formatInterval(interval)}"
  {value}
  {options}
  {disabled}
  onchange={choose}
/>
