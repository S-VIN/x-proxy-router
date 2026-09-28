import { describe, expect, it } from 'vitest';
import favicon from '../../public/favicon.svg?raw';
import { logoSvg, logoUrl } from './logo';
import { linkState } from './stores/linkStatus.svelte';

describe('linkState', () => {
  const server = (rating: number | null) => ({ rating });

  it('is working while traffic goes through a server that did not fail its check', () => {
    expect(linkState('online', server(80), false)).toBe('working');
    expect(linkState('online', server(null), false)).toBe('working');
    expect(linkState('connecting', server(80), false)).toBe('working');
  });

  it('fails without the x-proxy-router server, on rating 0 and after a lost connection', () => {
    expect(linkState('offline', server(80), false)).toBe('failed');
    expect(linkState('online', server(0), false)).toBe('failed');
    expect(linkState('online', null, true)).toBe('failed');
  });

  it('is none when no server is connected', () => {
    expect(linkState('online', null, false)).toBe('none');
    expect(linkState('connecting', null, false)).toBe('none');
  });
});

describe('logo', () => {
  it('ships the "none" logo as the static favicon', () => {
    expect(favicon).toBe(logoSvg('none'));
  });

  it('differs by state and makes data URLs', () => {
    expect(new Set([logoSvg('none'), logoSvg('working'), logoSvg('failed')]).size).toBe(3);
    expect(logoUrl('working')).toMatch(/^data:image\/svg\+xml,%3Csvg/);
  });
});
