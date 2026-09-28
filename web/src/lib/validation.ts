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
 * Why the value cannot be added as a name filter, or null. The syntax is Python's,
 * so only the server checks it. Spaces are part of an expression and kept.
 */
export function regFilterError(value: string, filters: readonly RegFilter[]): string | null {
  if (!value.trim()) return 'Enter a regular expression.';
  if (filters.some((filter) => filter.reg === value)) return 'This filter is already added.';
  return null;
}

export interface TestErrors {
  alias?: string;
  url?: string;
}

/** Per-test problems, index-aligned with `tests`; empty objects when valid. */
export function validateTests(tests: readonly OutboundTest[]): TestErrors[] {
  const seen = new Map<string, number>();
  return tests.map((test) => {
    const errors: TestErrors = {};
    const alias = test.alias.trim();
    if (!alias) {
      errors.alias = 'Enter a name.';
    } else {
      const count = (seen.get(alias) ?? 0) + 1;
      seen.set(alias, count);
      if (count > 1) errors.alias = 'This name is already used.';
    }
    const urlError = httpUrlError(test.url);
    if (urlError) errors.url = urlError;
    return errors;
  });
}

export function hasErrors(errors: readonly TestErrors[]): boolean {
  return errors.some((error) => error.alias !== undefined || error.url !== undefined);
}
