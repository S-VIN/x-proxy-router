import type { FilterReason, TestRule } from './api/protocol';

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'caution' | 'danger';

export const EMPTY = '—';

/** Number of categorical colors, --color-tag-1 … --color-tag-N in tokens.css. */
export const TAG_COLORS = 8;

export function formatPing(ms: number | null): string {
  return ms === null ? EMPTY : `${ms} ms`;
}

export function pingTone(ms: number | null): Tone {
  if (ms === null) return 'neutral';
  if (ms < 120) return 'success';
  if (ms < 250) return 'warning';
  return 'caution';
}

/** Bytes per second as bits per second; 0 means the download failed. */
export function formatSpeed(bytesPerSecond: number | null): string {
  if (bytesPerSecond === null) return EMPTY;
  if (bytesPerSecond === 0) return 'failed';
  const kbits = (bytesPerSecond * 8) / 1000;
  if (kbits < 1000) return `${Math.round(kbits)} kbit/s`;
  const mbits = kbits / 1000;
  return `${mbits < 10 ? mbits.toFixed(1) : Math.round(mbits)} Mbit/s`;
}

export function ratingTone(rating: number | null): Tone {
  if (rating === null) return 'neutral';
  if (rating >= 70) return 'success';
  if (rating >= 40) return 'warning';
  if (rating > 0) return 'caution';
  return 'danger';
}

export type IntervalUnit = 'minutes' | 'hours' | 'days';

export const UNIT_SECONDS: Record<IntervalUnit, number> = {
  minutes: 60,
  hours: 3600,
  days: 86400,
};

/** The largest unit that expresses the interval exactly, for editing. */
export function splitInterval(seconds: number): { value: number; unit: IntervalUnit } {
  for (const unit of ['days', 'hours', 'minutes'] as const) {
    if (seconds % UNIT_SECONDS[unit] === 0) return { value: seconds / UNIT_SECONDS[unit], unit };
  }
  return { value: Math.max(1, Math.round(seconds / 60)), unit: 'minutes' };
}

/** "every 6 hours", "every day", "every 90 seconds". */
export function formatInterval(seconds: number): string {
  if (seconds % 60 !== 0) return `every ${seconds} seconds`;
  const { value, unit } = splitInterval(seconds);
  const singular = unit.slice(0, -1);
  return value === 1 ? `every ${singular}` : `every ${value} ${unit}`;
}

const RULE_LABELS: Record<string, string> = {
  status_204: 'Status 204',
  status_2xx: 'Status 2xx',
  status_below_400: 'Below 400',
  status_below_500: 'Below 500',
  status_below_503: 'Below 503',
  any_status: 'Any status',
};

export const TEST_RULES: TestRule[] = Object.keys(RULE_LABELS);

export function ruleLabel(rule: TestRule): string {
  return RULE_LABELS[rule] ?? rule;
}

/** "sub.example.com" for "https://sub.example.com". */
export function hostLabel(urlShort: string): string {
  return urlShort.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '');
}

// Second-level labels of country domains such as co.uk or com.ru.
const SECOND_LEVEL = new Set(['ac', 'co', 'com', 'edu', 'gov', 'ne', 'net', 'or', 'org']);

/** The site name: "example" for "https://sub.example.com" or "https://example.co.uk". */
export function siteLabel(urlShort: string): string {
  const host = hostLabel(urlShort)
    .replace(/[/?#].*$/, '')
    .replace(/:\d+$/, '');
  if (host.startsWith('[') || /^[\d.]+$/.test(host)) return host;
  const [top = '', second = '', third = ''] = host.split('.').reverse();
  if (!second) return host;
  if (third && top.length === 2 && SECOND_LEVEL.has(second)) return third;
  return second;
}

/** Site names of the items' URLs by id, numbered when several share one: "alpha (1)". */
export function siteLabels<T extends { id: string }>(
  items: readonly T[],
  url: (item: T) => string,
): Map<string, string> {
  const sites = new Map(items.map((item) => [item.id, siteLabel(url(item))]));
  const totals = new Map<string, number>();
  for (const site of sites.values()) totals.set(site, (totals.get(site) ?? 0) + 1);
  const seen = new Map<string, number>();
  const labels = new Map<string, string>();
  for (const [id, site] of sites) {
    const index = (seen.get(site) ?? 0) + 1;
    seen.set(site, index);
    labels.set(id, (totals.get(site) ?? 0) > 1 ? `${site} (${index})` : site);
  }
  return labels;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

const PROTOCOL_LABELS: Record<string, string> = {
  vless: 'VLESS',
  shadowsocks: 'Shadowsocks',
  hysteria: 'Hysteria',
};

const TRANSPORT_LABELS: Record<string, string> = {
  tcp: 'TCP',
  grpc: 'gRPC',
  ws: 'WebSocket',
  xhttp: 'XHTTP',
  hysteria: 'QUIC',
};

const SECURITY_LABELS: Record<string, string> = {
  none: 'No TLS',
  tls: 'TLS',
  reality: 'Reality',
};

export function protocolLabel(protocol: string): string {
  return PROTOCOL_LABELS[protocol] ?? protocol;
}

export function transportLabel(transport: string): string {
  return TRANSPORT_LABELS[transport] ?? transport;
}

export function securityLabel(security: string): string {
  return SECURITY_LABELS[security] ?? security;
}

/** "VLESS · TCP · Reality"; Hysteria has its own QUIC transport and TLS, so it is "Hysteria 2". */
export function stackLabel(server: {
  protocol: string;
  transport: string;
  security: string;
}): string {
  if (server.protocol === 'hysteria' && server.transport === 'hysteria') return 'Hysteria 2';
  return [
    protocolLabel(server.protocol),
    transportLabel(server.transport),
    securityLabel(server.security),
  ].join(' · ');
}

const FILTER_TEXTS: Record<string, string> = {
  by_reg_filter: 'Its name matches a filter. Checks skip it.',
  by_ping: 'It did not answer the ping in the last check. Checks keep trying it.',
  by_subscription: 'Its subscription filters it.',
};

/** Why the server is filtered and whether checks can bring it back. */
export function filterText(reason: FilterReason): string {
  return FILTER_TEXTS[reason] ?? `Filtered: ${reason}.`;
}

export function yesNo(value: boolean): string {
  return value ? 'Yes' : 'No';
}
