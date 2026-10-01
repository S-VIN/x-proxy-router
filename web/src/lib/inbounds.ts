import type { InboundServer, InboundSettings, InboundType } from './api/protocol';

export interface InboundTypeInfo {
  type: InboundType;
  label: string;
  /** What it is and how apps use it, shown when choosing the type. */
  description: string;
}

/** Types a new inbound can have, in the order they are offered. */
export const INBOUND_TYPES: readonly InboundTypeInfo[] = [
  {
    type: 'proxy',
    label: 'Proxy',
    description:
      'SOCKS5 and HTTP on one port, UDP included. Set it as the proxy in a browser, an app or the system settings.',
  },
];

/** Problems by model field name, e.g. proxy_port; empty when the values can be sent. */
export type FieldErrors = Partial<Record<string, string>>;

export function inboundTypeLabel(type: InboundType): string {
  return INBOUND_TYPES.find((info) => info.type === type)?.label ?? type;
}

/** "127.0.0.1:20808" or "[::]:1080"; null for types without an address. */
export function inboundAddress(inbound: InboundServer): string | null {
  const { proxy_listen: listen, proxy_port: port } = inbound;
  if (listen === null || port === null) return null;
  return `${listen.includes(':') ? `[${listen}]` : listen}:${port}`;
}

const LOOPBACK = /^(127\.\d+\.\d+\.\d+|::1)$/;
const ANY_ADDRESS = new Set(['0.0.0.0', '::']);

/** "Proxy · this computer · no login". */
export function inboundDetails(inbound: InboundServer): string {
  const parts = [inboundTypeLabel(inbound.type)];
  const listen = inbound.proxy_listen;
  if (listen !== null) {
    if (LOOPBACK.test(listen)) parts.push('this computer');
    else if (ANY_ADDRESS.has(listen)) parts.push('local network');
  }
  if (inbound.type === 'proxy') {
    parts.push(inbound.proxy_username === null ? 'no login' : `login ${inbound.proxy_username}`);
  }
  return parts.join(' · ');
}

/** Choice of the proxy form for an address typed by hand. */
export const LISTEN_OTHER = 'other';

export const LISTEN_CHOICES = [
  { value: '127.0.0.1', label: 'This computer' },
  { value: '0.0.0.0', label: 'Local network' },
  { value: '::', label: 'Network, IPv6 too' },
  { value: LISTEN_OTHER, label: 'Other address…' },
] as const;

/** Values of the proxy form as typed. */
export interface ProxyDraft {
  /** A value of LISTEN_CHOICES; LISTEN_OTHER takes `address`. */
  listen: string;
  address: string;
  port: string;
  auth: boolean;
  username: string;
  /** Empty while editing an inbound with a password keeps that password. */
  password: string;
}

/** The first port from 1080 up that no inbound uses. */
export function freePort(inbounds: readonly InboundServer[]): number {
  const used = new Set(inbounds.map((inbound) => inbound.proxy_port));
  let port = 1080;
  while (used.has(port)) port += 1;
  return port;
}

export function proxyDraft(
  inbound: InboundServer | null,
  inbounds: readonly InboundServer[],
): ProxyDraft {
  const listen = inbound?.proxy_listen ?? '127.0.0.1';
  const preset = LISTEN_CHOICES.some((choice) => choice.value === listen);
  return {
    listen: preset ? listen : LISTEN_OTHER,
    address: preset ? '' : listen,
    port: String(inbound?.proxy_port ?? freePort(inbounds)),
    auth: inbound?.proxy_username != null,
    username: inbound?.proxy_username ?? '',
    password: '',
  };
}

/** The address the proxy listens on. */
export function proxyListen(draft: ProxyDraft): string {
  return draft.listen === LISTEN_OTHER ? draft.address.trim() : draft.listen;
}

/** Whole numbers 1–65535, or null. */
function parsePort(text: string): number | null {
  const value = text.trim();
  if (!/^\d+$/.test(value)) return null;
  const port = Number(value);
  return port >= 1 && port <= 65535 ? port : null;
}

/** Problems the server would reject; it checks the address and free ports itself. */
export function proxyErrors(
  draft: ProxyDraft,
  inbound: InboundServer | null,
  inbounds: readonly InboundServer[],
): FieldErrors {
  const errors: FieldErrors = {};
  if (!proxyListen(draft)) errors.proxy_listen = 'Enter an IP address.';
  const port = parsePort(draft.port);
  if (port === null) {
    errors.proxy_port = 'Enter a port from 1 to 65535.';
  } else if (inbounds.some((other) => other.id !== inbound?.id && other.proxy_port === port)) {
    errors.proxy_port = 'Another inbound uses this port.';
  }
  if (draft.auth) {
    const username = draft.username.trim();
    if (!username) errors.proxy_username = 'Enter a login.';
    else if (username.includes(':')) errors.proxy_username = 'A login cannot contain a colon.';
    if (!draft.password && inbound?.proxy_username == null) {
      errors.proxy_password = 'Enter a password.';
    }
  }
  return errors;
}

/** Settings of a new inbound, or of a stored one: then only those that differ. */
export function proxySettings(draft: ProxyDraft, inbound: InboundServer | null): InboundSettings {
  const settings: InboundSettings = {};
  const listen = proxyListen(draft);
  if (listen !== inbound?.proxy_listen) settings.proxy_listen = listen;
  const port = Number(draft.port.trim());
  if (port !== inbound?.proxy_port) settings.proxy_port = port;
  if (draft.auth) {
    const username = draft.username.trim();
    if (username !== inbound?.proxy_username) settings.proxy_username = username;
    if (draft.password) settings.proxy_password = draft.password;
  } else if (inbound?.proxy_username != null) {
    settings.proxy_username = null;
    settings.proxy_password = null;
  }
  return settings;
}

/** The proxy accepts connections from the network without a login. */
export function proxyOpen(draft: ProxyDraft): boolean {
  const listen = proxyListen(draft);
  return !draft.auth && listen !== '' && !LOOPBACK.test(listen);
}

/**
 * Form values of one inbound type. A new type adds a member here, cases to the
 * functions below and its fields component to InboundForm.
 */
export type InboundDraft = { type: 'proxy'; proxy: ProxyDraft };

/** Model fields each type's form shows, so the server's errors find their place. */
const DRAFT_FIELDS: Record<InboundDraft['type'], readonly string[]> = {
  proxy: ['proxy_listen', 'proxy_port', 'proxy_username', 'proxy_password'],
};

/** Form values for a new inbound of the type or for a stored one; null for unknown types. */
export function inboundDraft(
  type: InboundType,
  inbound: InboundServer | null,
  inbounds: readonly InboundServer[],
): InboundDraft | null {
  if (type === 'proxy') return { type: 'proxy', proxy: proxyDraft(inbound, inbounds) };
  return null;
}

export function draftErrors(
  draft: InboundDraft,
  inbound: InboundServer | null,
  inbounds: readonly InboundServer[],
): FieldErrors {
  switch (draft.type) {
    case 'proxy':
      return proxyErrors(draft.proxy, inbound, inbounds);
  }
}

export function draftSettings(draft: InboundDraft, inbound: InboundServer | null): InboundSettings {
  switch (draft.type) {
    case 'proxy':
      return proxySettings(draft.proxy, inbound);
  }
}

export function draftFields(draft: InboundDraft): readonly string[] {
  return DRAFT_FIELDS[draft.type];
}
