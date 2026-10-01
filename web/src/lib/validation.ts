import type { OutboundTest, RegFilter } from './api/protocol';

/** Why the value is not an http(s) URL with a host, or null when it is. */
export function httpUrlError(value: string): string | null {
  const text = value.trim();
  if (!text) return 'Enter a link.';
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return 'This is not a link.';
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return 'Use an http:// or https:// link.';
  }
  if (!url.hostname) return 'The link has no host.';
  return null;
}

/**
 * Why the value cannot be added as a name filter, or null. Any characters may be
 * in a pattern; spaces are part of it and kept.
 */
export function regFilterError(value: string, filters: readonly RegFilter[]): string | null {
  if (!value.trim()) return 'Enter a pattern.';
  if (filters.some((filter) => filter.reg === value)) return 'This filter is already added.';
  return null;
}

/** Why the value cannot be added as a test URL, or null. */
export function testUrlError(value: string, tests: readonly OutboundTest[]): string | null {
  const url = value.trim();
  if (!url) return 'Enter a URL.';
  const error = httpUrlError(url);
  if (error) return error;
  if (tests.some((test) => test.url === url)) return 'A test with this URL already exists.';
  return null;
}
