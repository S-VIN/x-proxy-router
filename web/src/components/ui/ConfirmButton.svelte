<script lang="ts">
  import type { IconName } from './Icon.svelte';
  import Button from './Button.svelte';

  interface Props {
    /** Name of the action, e.g. "Delete"; the first button shows only the icon. */
    label: string;
    icon: IconName;
    /** Text of the button that performs the action. */
    confirmLabel?: string;
    onconfirm: () => void;
    busy?: boolean;
    disabled?: boolean;
  }

  let {
    label,
    icon,
    confirmLabel = label,
    onconfirm,
    busy = false,
    disabled = false,
  }: Props = $props();

  // The action runs only on a second, explicit click; the page has no dialogs.
  let armed = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  function arm() {
    armed = true;
    clearTimeout(timer);
    timer = setTimeout(() => (armed = false), 5000);
  }

  function disarm() {
    clearTimeout(timer);
    armed = false;
  }

  function confirm() {
    disarm();
    onconfirm();
  }

  function focusOnMount(button: HTMLElement) {
    button.querySelector('button')?.focus();
  }

  $effect(() => () => clearTimeout(timer));
</script>

{#if armed && !busy}
  <span class="confirm" {@attach focusOnMount}>
    <Button variant="danger" size="sm" onclick={confirm} {disabled}>{confirmLabel}</Button>
    <Button variant="flat" size="sm" icon="close" label="Cancel" onclick={disarm} />
  </span>
{:else}
  <Button variant="flat" size="sm" {icon} {label} {busy} {disabled} onclick={arm} />
{/if}

<style>
  .confirm {
    display: inline-flex;
    gap: var(--space-1);
  }
</style>
