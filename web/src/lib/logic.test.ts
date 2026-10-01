import { describe, expect, it } from 'vitest';
import type { InboundServer, OutboundServer } from './api/protocol';
import {
  filterText,
  formatInterval,
  formatPing,
  formatRelative,
  formatSpeed,
  siteLabel,
  splitInterval,
  stackLabel,
} from './format';
import {
  freePort,
  inboundAddress,
  inboundDetails,
  inboundDraft,
  LISTEN_OTHER,
  proxyDraft,
  proxyErrors,
  proxyOpen,
  proxySettings,
  type ProxyDraft,
} from './inbounds';
import { COMPARATORS, filteredLast, keepOrder } from './ordering';
import { actionInfo, catchAllIndex, normalizedPattern, routingPatternError } from './routing';
import { hasErrors, httpUrlError, regFilterError, validateTests } from './validation';

function server(id: string, fields: Partial<OutboundServer>): OutboundServer {
  return { id, name: id, rating: null, ping: null, speed: null, ...fields } as OutboundServer;
}

describe('format', () => {
  it('formats ping and speed', () => {
    expect(formatPing(null)).toBe('—');
    expect(formatPing(42)).toBe('42 ms');
    expect(formatSpeed(null)).toBe('—');
    expect(formatSpeed(0)).toBe('failed');
    expect(formatSpeed(12_500)).toBe('100 kbit/s');
    expect(formatSpeed(250_000)).toBe('2.0 Mbit/s');
    expect(formatSpeed(5_000_000)).toBe('40 Mbit/s');
  });

  it('formats and splits intervals', () => {
    expect(formatInterval(3600)).toBe('every hour');
    expect(formatInterval(86400)).toBe('every day');
    expect(formatInterval(5400)).toBe('every 90 minutes');
    expect(formatInterval(45)).toBe('every 45 seconds');
    expect(splitInterval(2 * 86400)).toEqual({ value: 2, unit: 'days' });
    expect(splitInterval(7200)).toEqual({ value: 2, unit: 'hours' });
    expect(splitInterval(90)).toEqual({ value: 2, unit: 'minutes' });
  });

  it('formats relative times', () => {
    const now = Date.parse('2026-09-27T12:00:00Z');
    expect(formatRelative('2026-09-27T11:59:50Z', now)).toBe('just now');
    expect(formatRelative('2026-09-27T11:55:00Z', now)).toBe('5 min. ago');
    expect(formatRelative('2026-09-27T09:00:00.123456Z', now)).toBe('3 hr. ago');
    expect(formatRelative('2026-09-26T12:00:00Z', now)).toBe('yesterday');
  });

  it('names the site of a link', () => {
    expect(siteLabel('https://sub.provider.com')).toBe('provider');
    expect(siteLabel('https://provider.co.uk:8443')).toBe('provider');
    expect(siteLabel('https://vpn.abc.io')).toBe('abc');
    expect(siteLabel('https://provider.cc')).toBe('provider');
    expect(siteLabel('http://10.0.0.1:2096')).toBe('10.0.0.1');
    expect(siteLabel('http://[::1]:8080')).toBe('[::1]');
    expect(siteLabel('http://localhost')).toBe('localhost');
  });

  it('names the protocol stack', () => {
    expect(stackLabel({ protocol: 'vless', transport: 'ws', security: 'tls' })).toBe(
      'VLESS · WebSocket · TLS',
    );
    expect(stackLabel({ protocol: 'hysteria', transport: 'hysteria', security: 'tls' })).toBe(
      'Hysteria 2',
    );
    expect(stackLabel({ protocol: 'trojan', transport: 'tcp', security: 'tls' })).toBe(
      'trojan · TCP · TLS',
    );
  });

  it('explains filter reasons, new ones as is', () => {
    expect(filterText('by_reg_filter')).toContain('name matches a filter');
    expect(filterText('by_country')).toBe('Filtered: by_country.');
  });
});

describe('ordering', () => {
  it('sorts by rating with unchecked servers last', () => {
    const list = [
      server('a', { rating: null }),
      server('b', { rating: 50, ping: 90 }),
      server('c', { rating: 80 }),
      server('d', { rating: 50, ping: 40 }),
    ];
    expect(list.sort(COMPARATORS.rating).map((s) => s.id)).toEqual(['c', 'd', 'b', 'a']);
  });

  it('sorts names naturally', () => {
    const list = [server('x', { name: 'NL 10' }), server('y', { name: 'nl 2' })];
    expect(list.sort(COMPARATORS.name).map((s) => s.id)).toEqual(['y', 'x']);
  });

  it('keeps the previous order and appends new items sorted', () => {
    const items = [
      server('a', { rating: 10 }),
      server('b', { rating: 90 }),
      server('new1', { rating: 5 }),
      server('new2', { rating: 60 }),
    ];
    const order = keepOrder(['b', 'gone', 'a'], items, COMPARATORS.rating);
    expect(order.map((s) => s.id)).toEqual(['b', 'a', 'new2', 'new1']);
  });

  it('puts filtered servers last, each group in the chosen order', () => {
    const list = [
      server('a', { rating: 95, filtered: 'by_reg_filter' }),
      server('b', { rating: 40, filtered: null }),
      server('c', { rating: 0, filtered: 'by_ping' }),
      server('d', { rating: 70, filtered: null }),
    ];
    expect(list.sort(filteredLast(COMPARATORS.rating)).map((s) => s.id)).toEqual([
      'd',
      'b',
      'a',
      'c',
    ]);
  });
});

describe('validation', () => {
  it('accepts only http(s) links with a host', () => {
    expect(httpUrlError('https://sub.example/x?token=1')).toBeNull();
    expect(httpUrlError('  ')).not.toBeNull();
    expect(httpUrlError('ftp://sub.example')).not.toBeNull();
    expect(httpUrlError('sub.example')).not.toBeNull();
  });

  it('checks test names and URLs', () => {
    const errors = validateTests([
      { alias: 'google', url: 'https://www.gstatic.com/generate_204', rule: 'status_204' },
      { alias: ' google ', url: 'https://example.com', rule: 'any_status' },
      { alias: '', url: 'nope', rule: 'any_status' },
    ]);
    expect(errors[0]).toEqual({});
    expect(errors[1]?.alias).toBeDefined();
    expect(errors[2]).toMatchObject({ alias: expect.any(String), url: expect.any(String) });
    expect(hasErrors(errors)).toBe(true);
    expect(hasErrors([{}])).toBe(false);
  });

  it('checks new name filters, keeping any characters', () => {
    const filters = [{ id: '1', reg: 'RU*' }];
    expect(regFilterError('*russia*', filters)).toBeNull();
    expect(regFilterError('(?i)[RU', filters)).toBeNull();
    expect(regFilterError(' RU*', filters)).toBeNull();
    expect(regFilterError('  ', filters)).not.toBeNull();
    expect(regFilterError('RU*', filters)).not.toBeNull();
  });
});

function inbound(fields: Partial<InboundServer> = {}): InboundServer {
  return {
    id: 'a',
    type: 'proxy',
    enabled: true,
    proxy_listen: '127.0.0.1',
    proxy_port: 20808,
    proxy_username: null,
    error: null,
    ...fields,
  };
}

function draft(fields: Partial<ProxyDraft> = {}): ProxyDraft {
  return {
    listen: '127.0.0.1',
    address: '',
    port: '1080',
    auth: false,
    username: '',
    password: '',
    ...fields,
  };
}

describe('inbounds', () => {
  it('describe the address, the reach and the login', () => {
    expect(inboundAddress(inbound())).toBe('127.0.0.1:20808');
    expect(inboundAddress(inbound({ proxy_listen: '::' }))).toBe('[::]:20808');
    expect(inboundDetails(inbound())).toBe('Proxy · this computer · no login');
    expect(inboundDetails(inbound({ proxy_listen: '0.0.0.0', proxy_username: 'alice' }))).toBe(
      'Proxy · local network · login alice',
    );
    expect(inboundDetails(inbound({ proxy_listen: '192.168.1.5' }))).toBe('Proxy · no login');
    const tunnel = inbound({ type: 'tun', proxy_listen: null, proxy_port: null });
    expect(inboundAddress(tunnel)).toBeNull();
    expect(inboundDetails(tunnel)).toBe('tun');
    expect(inboundDraft('tun', tunnel, [])).toBeNull();
  });

  it('suggest a port no inbound uses', () => {
    expect(freePort([])).toBe(1080);
    expect(freePort([inbound({ proxy_port: 1080 }), inbound({ proxy_port: 1081 })])).toBe(1082);
  });

  it('fill the proxy form from an inbound or with defaults', () => {
    expect(proxyDraft(null, [inbound({ proxy_port: 1080 })])).toEqual(draft({ port: '1081' }));
    expect(
      proxyDraft(inbound({ proxy_listen: '192.168.1.5', proxy_username: 'alice' }), []),
    ).toEqual(
      draft({
        listen: LISTEN_OTHER,
        address: '192.168.1.5',
        port: '20808',
        auth: true,
        username: 'alice',
      }),
    );
  });

  it('check the proxy form before the server does', () => {
    const others = [inbound({ id: 'b', proxy_port: 1080 })];
    expect(proxyErrors(draft({ port: '1081' }), null, others)).toEqual({});
    expect(proxyErrors(draft(), inbound({ id: 'b' }), others)).toEqual({});
    expect(proxyErrors(draft(), null, others).proxy_port).toBe('Another inbound uses this port.');
    for (const port of ['', '0', '65536', '10.5', 'x']) {
      expect(proxyErrors(draft({ port }), null, []).proxy_port).toBeDefined();
    }
    expect(proxyErrors(draft({ listen: LISTEN_OTHER }), null, []).proxy_listen).toBeDefined();
    const auth = draft({ auth: true, username: 'a:b' });
    expect(Object.keys(proxyErrors(auth, null, []))).toEqual(['proxy_username', 'proxy_password']);
    // A stored password is kept when the field is empty.
    const stored = inbound({ proxy_username: 'alice' });
    expect(proxyErrors(draft({ auth: true, username: 'bob' }), stored, [])).toEqual({});
  });

  it('send all settings of a new proxy and only the changed ones of a stored proxy', () => {
    expect(proxySettings(draft({ auth: true, username: ' alice ', password: 'p' }), null)).toEqual({
      proxy_listen: '127.0.0.1',
      proxy_port: 1080,
      proxy_username: 'alice',
      proxy_password: 'p',
    });
    const stored = inbound({ proxy_username: 'alice' });
    const unchanged = proxyDraft(stored, []);
    expect(proxySettings(unchanged, stored)).toEqual({});
    expect(proxySettings({ ...unchanged, password: 'new' }, stored)).toEqual({
      proxy_password: 'new',
    });
    expect(proxySettings({ ...unchanged, listen: '0.0.0.0', port: '1081' }, stored)).toEqual({
      proxy_listen: '0.0.0.0',
      proxy_port: 1081,
    });
    expect(proxySettings({ ...unchanged, auth: false }, stored)).toEqual({
      proxy_username: null,
      proxy_password: null,
    });
  });

  it('warn about a proxy open to the network', () => {
    expect(proxyOpen(draft())).toBe(false);
    expect(proxyOpen(draft({ listen: '0.0.0.0' }))).toBe(true);
    expect(proxyOpen(draft({ listen: '0.0.0.0', auth: true }))).toBe(false);
    expect(proxyOpen(draft({ listen: LISTEN_OTHER }))).toBe(false);
    expect(proxyOpen(draft({ listen: LISTEN_OTHER, address: '::1' }))).toBe(false);
  });
});

describe('routing', () => {
  const rules = [{ id: 'r1', priority: 1, reg: '*.youtube.com', action: 'proxy' }];

  it('normalize patterns as the server keeps them', () => {
    expect(normalizedPattern(' *.YouTube.com ')).toBe('*.youtube.com');
    expect(normalizedPattern('a***b')).toBe('a*b');
  });

  it('accept the patterns the server accepts', () => {
    for (const reg of ['youtube.com', '*google*', 'my_host-1', '192.168.*', '10.*', '1.2.3.4']) {
      expect(routingPatternError(reg, rules), reg).toBeNull();
    }
    for (const reg of ['*', '::1', '2001:DB8::1', '0.0.0.0', '255.255.255.*']) {
      expect(routingPatternError(reg, rules), reg).toBeNull();
    }
  });

  it('reject the patterns the server rejects', () => {
    const ip = 'In an IP address * replaces whole numbers at the end, e.g. 192.168.*';
    for (const reg of [
      '192.16*',
      '192.*.1.1',
      '*.1',
      '256.1.1.1',
      '01.2.3.4',
      '1.2.3',
      '1.2.3.4.*',
    ]) {
      expect(routingPatternError(reg, rules), reg).toBe(ip);
    }
    for (const reg of ['you tube.com', 'пример.рф', 'a/b', 'a?']) {
      expect(routingPatternError(reg, rules), reg).toContain('Latin letters');
    }
    expect(routingPatternError('fe80::*', rules)).toContain('IPv6');
    expect(routingPatternError('  ', rules)).not.toBeNull();
  });

  it('reject a pattern of another rule, as the server compares them', () => {
    expect(routingPatternError('*.YouTube.com', rules)).toContain('already exists');
    expect(routingPatternError('**.youtube.com', rules)).toContain('already exists');
    expect(routingPatternError('*.youtube.com', rules, 'r1')).toBeNull();
  });

  it('find the rule that catches everything', () => {
    expect(catchAllIndex(rules)).toBe(-1);
    expect(catchAllIndex([...rules, { id: 'r2', priority: 2, reg: '*', action: 'direct' }])).toBe(
      1,
    );
  });

  it('label actions, new ones as is', () => {
    expect(actionInfo('direct').label).toBe('Direct');
    expect(actionInfo('reroute')).toEqual({ label: 'reroute', tone: 'neutral', text: 'reroute' });
  });
});
