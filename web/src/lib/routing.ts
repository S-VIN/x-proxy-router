import type { RoutingAction, RoutingRule } from './api/protocol';
import type { Tone } from './format';

export interface ActionInfo {
  label: string;
  tone: Tone;
  /** Where the traffic goes. */
  text: string;
}

const ACTIONS: Record<string, ActionInfo> = {
  proxy: {
    label: 'Via server',
    tone: 'accent',
    text: 'Through the connected server; blocked while none is connected.',
  },
  direct: {
    label: 'Direct',
    tone: 'success',
    text: 'Straight from this computer, without a server.',
  },
  block: { label: 'Block', tone: 'danger', text: 'The connection is closed at once.' },
};

export const ROUTING_ACTIONS: RoutingAction[] = Object.keys(ACTIONS);

/** Label, tone and explanation; an action of a newer server is shown as is. */
export function actionInfo(action: RoutingAction): ActionInfo {
  return ACTIONS[action] ?? { label: action, tone: 'neutral', text: action };
}

/** The pattern as the server keeps it: lower case, ** as *; spaces around are dropped. */
export function normalizedPattern(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\*{2,}/g, '*');
}

// Patterns of digits, dots and * with a digit are IPv4: no domain ends with a number.
const IPV4_LIKE = /^[\d.*]*\d[\d.*]*$/;
// Leading whole octets, each followed by a dot, then the wildcard: 192.168.*
const IPV4_PREFIX = /^((?:\d{1,3}\.){1,3})\*$/;
const DOMAIN = /^[a-z0-9._*-]+$/;

function isOctet(text: string): boolean {
  return /^(0|[1-9]\d{0,2})$/.test(text) && Number(text) <= 255;
}

function isIpv4Pattern(pattern: string): boolean {
  const prefix = IPV4_PREFIX.exec(pattern);
  const octets = prefix ? (prefix[1] ?? '').split('.').slice(0, -1) : pattern.split('.');
  return (prefix !== null || octets.length === 4) && octets.every(isOctet);
}

/**
 * Why the server would reject the pattern of a new rule, or null. The rules of the
 * server/PROTOCOL.md routing_rule model; the server checks IPv6 addresses itself.
 */
export function routingPatternError(value: string, rules: readonly RoutingRule[]): string | null {
  const pattern = normalizedPattern(value);
  if (!pattern) return 'Enter a domain or an IP address.';
  if (pattern.includes(':')) {
    if (pattern.includes('*')) return 'An IPv6 address cannot have *: enter the whole address.';
  } else if (IPV4_LIKE.test(pattern)) {
    if (!isIpv4Pattern(pattern)) {
      return 'In an IP address * replaces whole numbers at the end, e.g. 192.168.*';
    }
  } else if (!DOMAIN.test(pattern)) {
    return 'A domain may have only Latin letters, digits, -, _, . and *';
  }
  if (rules.some((rule) => rule.reg === pattern)) {
    return 'A rule for this address already exists.';
  }
  return null;
}

/** Index of the first rule for every address; the rules after it never match. -1 if none. */
export function catchAllIndex(rules: readonly RoutingRule[]): number {
  return rules.findIndex((rule) => rule.reg === '*');
}
