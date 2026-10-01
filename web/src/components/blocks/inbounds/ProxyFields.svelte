<script lang="ts">
  import { proxyOpen, type FieldErrors, type ProxyDraft } from '../../../lib/inbounds';
  import Switch from '../../ui/Switch.svelte';
  import TextField from '../../ui/TextField.svelte';

  interface Props {
    draft: ProxyDraft;
    errors: FieldErrors;
    /** The inbound already has a password, which an empty field keeps. */
    hasPassword: boolean;
    disabled: boolean;
  }

  let { draft = $bindable(), errors, hasPassword, disabled }: Props = $props();

  const id = $props.id();
</script>

<!-- Settings of a SOCKS5 and HTTP proxy inbound; InboundForm checks and sends them. -->
<div class="fields">
  <label class="label" for="{id}-listen">IP address</label>
  <div class="control">
    <TextField
      id="{id}-listen"
      size="sm"
      class="mono"
      placeholder="127.0.0.1"
      title="127.0.0.1: only this computer. 0.0.0.0: the local network too."
      bind:value={draft.listen}
      invalid={errors.proxy_listen !== undefined}
      {disabled}
    />
  </div>
  {#if errors.proxy_listen}
    <p class="invalid">{errors.proxy_listen}</p>
  {/if}

  <label class="label" for="{id}-port">Port</label>
  <div class="control">
    <TextField
      id="{id}-port"
      size="sm"
      class="num"
      inputmode="numeric"
      bind:value={draft.port}
      invalid={errors.proxy_port !== undefined}
      {disabled}
    />
  </div>
  {#if errors.proxy_port}
    <p class="invalid">{errors.proxy_port}</p>
  {/if}

  <label class="label" for="{id}-auth">Require login</label>
  <div class="control">
    <Switch
      id="{id}-auth"
      label="Require login"
      hideLabel
      checked={draft.auth}
      {disabled}
      onchange={(checked) => (draft.auth = checked)}
    />
  </div>
  {#if draft.auth}
    <label class="label" for="{id}-username">Login</label>
    <div class="control">
      <TextField
        id="{id}-username"
        size="sm"
        bind:value={draft.username}
        invalid={errors.proxy_username !== undefined}
        {disabled}
      />
    </div>
    {#if errors.proxy_username}
      <p class="invalid">{errors.proxy_username}</p>
    {/if}
    <label class="label" for="{id}-password">Password</label>
    <div class="control">
      <TextField
        id="{id}-password"
        size="sm"
        type="password"
        autocomplete="new-password"
        placeholder={hasPassword ? 'Unchanged' : undefined}
        bind:value={draft.password}
        invalid={errors.proxy_password !== undefined}
        {disabled}
      />
    </div>
    {#if errors.proxy_password}
      <p class="invalid">{errors.proxy_password}</p>
    {/if}
  {/if}

  {#if proxyOpen(draft)}
    <p class="note">Anyone who reaches this computer over the network can use the proxy.</p>
  {/if}
</div>

<style>
  /* Labels on the left, controls on the right; messages take both columns. */
  .fields {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }

  .label {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .control {
    display: flex;
    min-width: 0;
  }

  .control > :global(*) {
    flex: 1;
  }

  /* The switch keeps its size and starts where the fields do. */
  .fields .control > :global(.switch) {
    flex: none;
    padding-left: 0;
  }

  .invalid,
  .note {
    grid-column: 1 / -1;
    min-width: 0;
  }

  .invalid {
    color: var(--color-danger-text);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }

  .note {
    color: var(--color-warning-text);
    font-size: var(--text-xs);
  }
</style>
