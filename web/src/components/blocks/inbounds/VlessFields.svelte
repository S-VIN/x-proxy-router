<script lang="ts">
  import type { FieldErrors, VlessDraft } from '../../../lib/inbounds';
  import TextField from '../../ui/TextField.svelte';
  let {
    draft = $bindable(),
    errors,
    disabled,
  }: { draft: VlessDraft; errors: FieldErrors; disabled: boolean } = $props();
  const id = $props.id();
  const fields = [
    { key: 'listen', field: 'vless_listen', label: 'Listen IP', placeholder: '0.0.0.0' },
    { key: 'port', field: 'vless_port', label: 'Port', placeholder: '443' },
    {
      key: 'address',
      field: 'vless_address',
      label: 'Public IP or domain',
      placeholder: 'proxy.example.com',
    },
    {
      key: 'serverName',
      field: 'vless_server_name',
      label: 'TLS camouflage domain (SNI)',
      placeholder: 'www.example.com',
    },
  ] as const;
</script>

<p class="small muted">
  TCP + REALITY + Vision. Credentials are generated automatically. No unencrypted mode.
</p>
{#each fields as field}
  <label for="{id}-{field.key}" class="small">{field.label}</label>
  <TextField
    id="{id}-{field.key}"
    size="sm"
    bind:value={draft[field.key]}
    placeholder={field.placeholder}
    invalid={!!errors[field.field]}
    aria-describedby={errors[field.field] ? `${id}-${field.key}-error` : undefined}
    {disabled}
  />
  {#if errors[field.field]}<p id="{id}-{field.key}-error" class="small" role="alert">
      {errors[field.field]}
    </p>{/if}
{/each}
<p class="small muted">
  Use a reachable TLS 1.3 website on port 443 whose certificate matches this SNI. The public address
  is used in the exported link. REALITY cannot guarantee that a proxy will remain undetected.
</p>
