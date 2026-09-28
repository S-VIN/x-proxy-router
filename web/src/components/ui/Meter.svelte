<script lang="ts">
  import { EMPTY, ratingTone } from '../../lib/format';

  interface Props {
    /** 0–100, or null when unknown. */
    value: number | null;
    label: string;
  }

  let { value, label }: Props = $props();

  const tone = $derived(ratingTone(value));
</script>

<span
  class="meter {tone}"
  role="meter"
  aria-label={label}
  aria-valuemin={0}
  aria-valuemax={100}
  aria-valuenow={value ?? undefined}
  aria-valuetext={value === null ? 'Not checked' : undefined}
>
  <span class="track"><span class="fill" style:width="{value ?? 0}%"></span></span>
  <span class="value num">{value ?? EMPTY}</span>
</span>

<style>
  .meter {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    width: 100%;
  }

  .track {
    flex: 1;
    min-width: 24px;
    height: 6px;
    overflow: hidden;
    border-radius: var(--radius-full);
    background: var(--color-control);
  }

  .fill {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: var(--color-text-faint);
    transition: width var(--duration-normal) var(--easing);
  }

  .value {
    min-width: 2ch;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    text-align: right;
  }

  .success .fill {
    background: var(--color-success);
  }

  .warning .fill {
    background: var(--color-warning);
  }

  .caution .fill {
    background: var(--color-caution);
  }

  .danger .value {
    color: var(--color-danger-text);
  }

  .neutral .value {
    color: var(--color-text-faint);
  }
</style>
