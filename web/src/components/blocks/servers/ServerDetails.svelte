<script lang="ts">
  import type { OutboundServer, OutboundTest } from '../../../lib/api/protocol';
  import {
    filterText,
    formatPing,
    formatSpeed,
    pingTone,
    stackLabel,
    yesNo,
  } from '../../../lib/format';
  import { outboundTests } from '../../../lib/stores';
  import Icon from '../../ui/Icon.svelte';
  import Stat from '../../ui/Stat.svelte';

  interface Props {
    id: string;
    server: OutboundServer;
    tests: readonly OutboundTest[];
  }

  let { id, server, tests }: Props = $props();

  interface Entry {
    label: string;
    value: string;
    mono?: boolean;
  }

  // The rest of the fields, only those with values: protocol-specific ones are null
  // for other protocols, some are empty. Protocol, transport and security are in the
  // stats above; the subscription is in the row.
  const entries = $derived.by(() => {
    const s = server;
    const list: (Entry | false)[] = [
      { label: 'Address', value: `${s.address}:${s.port}`, mono: true },
      s.source_tag !== null && { label: 'Provider tag', value: s.source_tag },
      s.server_name !== null && { label: 'SNI', value: s.server_name, mono: true },
      s.fingerprint !== null && { label: 'Fingerprint', value: s.fingerprint },
      s.alpn.length > 0 && { label: 'ALPN', value: s.alpn.join(', ') },
      s.allow_insecure !== null && {
        label: 'Skip certificate check',
        value: yesNo(s.allow_insecure),
      },
      s.public_key !== null && { label: 'Reality public key', value: s.public_key, mono: true },
      s.short_id !== null && { label: 'Reality short ID', value: s.short_id, mono: true },
      s.spider_x !== null && { label: 'Reality SpiderX', value: s.spider_x, mono: true },
      s.host !== null && { label: 'Host', value: s.host, mono: true },
      s.path !== null && { label: 'Path', value: s.path, mono: true },
      s.service_name !== null && { label: 'gRPC service', value: s.service_name, mono: true },
      s.grpc_mode !== null && { label: 'gRPC mode', value: s.grpc_mode },
      s.xhttp_mode !== null && { label: 'XHTTP mode', value: s.xhttp_mode },
      s.vless_flow !== null && { label: 'VLESS flow', value: s.vless_flow || 'None' },
      s.shadowsocks_method !== null && { label: 'Cipher', value: s.shadowsocks_method },
      s.shadowsocks_udp_over_tcp !== null && {
        label: 'UDP over TCP',
        value:
          s.shadowsocks_udp_over_tcp && s.shadowsocks_uot_version !== null
            ? `Yes, version ${s.shadowsocks_uot_version}`
            : yesNo(s.shadowsocks_udp_over_tcp),
      },
      s.hysteria_version !== null && {
        label: 'Hysteria version',
        value: String(s.hysteria_version),
      },
      { label: 'Server ID', value: s.id, mono: true },
    ];
    return list.filter((entry): entry is Entry => entry !== false && entry.value !== '');
  });

  // Results of the current tests, in their order.
  const results = $derived(
    tests
      .map((test) => ({
        id: test.id,
        label: outboundTests.label(test.id),
        passed: server.tests?.[test.id] ?? null,
      }))
      .filter((item) => item.passed !== null),
  );
</script>

<!-- Part of the expanded row: it shares the row's background and its left edge. -->
<div class="details" {id}>
  {#if server.filtered !== null}
    <p class="filtered">
      <Icon name="filter" size={14} />
      <span>
        {server.is_connected
          ? 'Filtered: it stays connected, but cannot be connected again after a switch.'
          : 'Filtered: it cannot be connected.'}
        {filterText(server.filtered)}
      </span>
    </p>
  {/if}

  <dl class="stats">
    <Stat label="Ping" tone={pingTone(server.ping)}>{formatPing(server.ping)}</Stat>
    <Stat label="Speed" tone={server.speed === 0 ? 'danger' : 'neutral'}>
      {formatSpeed(server.speed)}
    </Stat>
    <Stat label="Protocol">{stackLabel(server)}</Stat>
    {#if results.length > 0}
      <div class="tests">
        <dt>Last tests</dt>
        <dd>
          <ul class="results">
            {#each results as item (item.id)}
              <li class="result" class:failed={!item.passed}>
                <Icon name={item.passed ? 'check' : 'close'} size={12} />
                {item.label}<span class="visually-hidden"
                  >: {item.passed ? 'passed' : 'failed'}</span
                >
              </li>
            {/each}
          </ul>
        </dd>
      </div>
    {/if}
  </dl>

  <!-- One line per value; long ones end with … and show whole on hover. -->
  <dl class="fields">
    {#each entries as entry (entry.label)}
      <div class="field">
        <dt>{entry.label}</dt>
        <dd class:mono={entry.mono} title={entry.value}>{entry.value}</dd>
      </div>
    {/each}
  </dl>
</div>

<style>
  .details {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: 2px var(--space-3) var(--space-3);
  }

  .filtered {
    display: flex;
    align-items: flex-start;
    gap: var(--space-1);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  /* In line with the first line of the text. */
  .filtered > :global(svg) {
    margin-top: 3px;
  }

  .stats {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-5);
  }

  dt {
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
  }

  .tests dd {
    display: flex;
    min-height: calc(var(--text-sm) * var(--leading-normal));
    align-items: center;
  }

  .results {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }

  .result {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 0 7px 0 5px;
    border-radius: var(--radius-full);
    background: var(--color-success-soft);
    color: var(--color-success-text);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    line-height: 1.5;
  }

  .result.failed {
    background: var(--color-danger-soft);
    color: var(--color-danger-text);
  }

  /* Everything else: quieter than the stats, in as many columns as fit. */
  .fields {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
    gap: var(--space-2) var(--space-4);
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }

  .field {
    min-width: 0;
  }

  .field dd {
    overflow: hidden;
    font-size: var(--text-sm);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
