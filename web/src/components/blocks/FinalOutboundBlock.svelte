<script lang="ts">
  import { connection, outboundServers, serverSettings } from '../../lib/stores';
  import { describeError, RequestError } from '../../lib/api/errors';
  import type { RequestPayload } from '../../lib/api/protocol';
  import Block from '../layout/Block.svelte';
  import Button from '../ui/Button.svelte';
  import Switch from '../ui/Switch.svelte';
  import Notice from '../ui/Notice.svelte';
  import TextField from '../ui/TextField.svelte';
  let { order }: { order: number } = $props();
  let uri = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let saved = $state(false);
  const settings = $derived(serverSettings.current);
  const serverMode = $derived(settings?.outbound_mode === 'server');
  const id = $props.id();
  async function change(values: Omit<RequestPayload<'change/server_settings'>, 'id'>) {
    busy = true;
    error = null;
    saved = false;
    try {
      await serverSettings.change(values);
      saved = true;
      if ('final_outbound_uri' in values) uri = '';
    } catch (reason) {
      error =
        reason instanceof RequestError && reason.code === 'validation_error'
          ? reason.message
          : describeError(reason);
    } finally {
      busy = false;
    }
  }
</script>

<Block
  title="Final outbound"
  icon="server"
  {order}
  hint="Choose direct server egress or send client traffic through a rotating first hop and a fixed final server."
>
  {#if settings}
    <Switch
      label="Server mode · direct Internet exit"
      checked={serverMode}
      {busy}
      disabled={!connection.ready}
      onchange={(on) => change({ outbound_mode: on ? 'server' : 'client' })}
    />
    {#if serverMode}
      <p class="small muted">
        All inbound traffic exits directly from this server. Routing rules and first-hop selection
        are ignored. Create a VLESS inbound below and copy its link to your client.
      </p>
    {:else}
      <p class="small muted">Client → selected first hop → final server → Internet</p>
      <form
        onsubmit={(event) => {
          event.preventDefault();
          change({ final_outbound_uri: uri.trim() });
        }}
      >
        <label class="small" for="{id}-uri">VLESS link exported by your server</label>
        <TextField
          id="{id}-uri"
          type="password"
          bind:value={uri}
          placeholder="vless://…"
          disabled={busy || !connection.ready}
        />
        <Button type="submit" size="sm" {busy} disabled={!connection.ready || !uri.trim()}
          >Save final server</Button
        >
      </form>
      <p class="small endpoint">{settings.final_outbound_address ?? 'No final server saved'}</p>
      <Switch
        label="Enable final outbound"
        checked={settings.final_outbound_enabled ?? false}
        {busy}
        disabled={!connection.ready || !settings.final_outbound_address}
        onchange={(on) => change({ final_outbound_enabled: on })}
      />
      {#if settings.final_outbound_enabled}
        <p class="small muted">
          All inbound traffic uses both hops, including destinations marked Direct in routing rules.
          Without either hop, traffic is blocked. Existing connections may keep their previous
          route; reconnect apps after switching.
        </p>
        {#if !outboundServers.connected}<Notice tone="warning"
            >Select a first-hop server or enable auto-connect to start the chain.</Notice
          >{/if}
      {:else}
        <p class="small muted">
          Final outbound is off. Client traffic follows the routing rules and selected first hop.
        </p>
      {/if}
      {#if settings.final_outbound_address}
        <Button
          size="sm"
          variant="flat"
          disabled={busy || !connection.ready}
          onclick={() => change({ final_outbound_enabled: false, final_outbound_uri: null })}
          >Remove final server</Button
        >
      {/if}
    {/if}
    {#if saved}<p class="small muted" role="status">Settings applied.</p>{/if}
    {#if error}<Notice tone="danger" ondismiss={() => (error = null)}>{error}</Notice>{/if}
  {:else}<p class="small muted">Loading…</p>{/if}
</Block>

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .endpoint {
    overflow-wrap: anywhere;
    font-family: var(--font-mono);
  }
</style>
