import type { LinkState } from './stores/linkStatus.svelte';

interface LogoColors {
  /** Top and bottom of the face gradient. */
  light: string;
  base: string;
  /** The middle and edges of the side under the face; also the dots in the nodes. */
  strong: string;
  dark: string;
}

// GNOME palette: blue when no server is connected, green when traffic goes through
// one, red on an error. The green is one step darker so the white lines stay visible.
const COLORS: Record<LinkState, LogoColors> = {
  none: { light: '#62a0ea', base: '#3584e4', strong: '#1c71d8', dark: '#1a5fb4' },
  working: { light: '#33d17a', base: '#2ec27e', strong: '#26a269', dark: '#1b7a4e' },
  failed: { light: '#ed333b', base: '#e01b24', strong: '#c01c28', dark: '#a51d2d' },
};

/** The logo as an SVG document; public/favicon.svg is the "none" one. */
export function logoSvg(state: LinkState): string {
  const { light, base, strong, dark } = COLORS[state];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="face" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${light}"/>
      <stop offset="1" stop-color="${base}"/>
    </linearGradient>
    <linearGradient id="side" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="${dark}"/>
      <stop offset="0.5" stop-color="${strong}"/>
      <stop offset="1" stop-color="${dark}"/>
    </linearGradient>
  </defs>
  <rect x="12" y="20" width="104" height="96" rx="24" fill="url(#side)"/>
  <rect x="12" y="12" width="104" height="96" rx="24" fill="url(#face)"/>
  <rect x="13" y="13" width="102" height="94" rx="23" fill="none" stroke="#ffffff" stroke-opacity="0.18" stroke-width="2"/>
  <g fill="none" stroke="#ffffff" stroke-linecap="round" stroke-width="7">
    <path d="M44 60 C 62 60, 64 36, 84 36" stroke-opacity="0.45"/>
    <path d="M44 60 C 62 60, 64 84, 84 84" stroke-opacity="0.45"/>
    <path d="M44 60 H 84"/>
  </g>
  <circle cx="90" cy="36" r="8" fill="#ffffff" fill-opacity="0.6"/>
  <circle cx="90" cy="84" r="8" fill="#ffffff" fill-opacity="0.6"/>
  <circle cx="38" cy="60" r="11" fill="#ffffff"/>
  <circle cx="38" cy="60" r="4.5" fill="${strong}"/>
  <circle cx="90" cy="60" r="11" fill="#ffffff"/>
  <circle cx="90" cy="60" r="5.5" fill="${strong}"/>
</svg>
`;
}

/** The logo as a data: URL, for an <img> or the favicon link. */
export function logoUrl(state: LinkState): string {
  return `data:image/svg+xml,${encodeURIComponent(logoSvg(state))}`;
}
