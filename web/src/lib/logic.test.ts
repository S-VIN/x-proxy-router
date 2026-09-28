import { describe, expect, it } from 'vitest';
import type { OutboundServer } from './api/protocol';
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
import { COMPARATORS, filteredLast, keepOrder } from './ordering';
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

  it('checks new name filters, leaving the syntax to the server', () => {
    const filters = [{ id: '1', reg: '^RU' }];
    expect(regFilterError('(?i)russia', filters)).toBeNull();
    expect(regFilterError('(unclosed', filters)).toBeNull();
    expect(regFilterError(' RU', filters)).toBeNull();
    expect(regFilterError('  ', filters)).not.toBeNull();
    expect(regFilterError('^RU', filters)).not.toBeNull();
  });
});
