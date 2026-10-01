<script lang="ts" module>
  // 16×16 symbolic icons drawn with strokes; "h.01" segments render as dots.
  const PATHS = {
    add: 'M8 3v10M3 8h10',
    alert: 'M8 2.5 14.5 13.5h-13zM8 6.5v3M8 11.5h.01',
    check: 'm3 8.5 3.2 3L13 4.5',
    'chevron-down': 'm4 6 4 4 4-4',
    close: 'm4 4 8 8M12 4l-8 8',
    edit: 'M10.5 2.5 13.5 5.5 6 13H3v-3zM9 4l3 3',
    filter: 'M2.5 3h11L9.5 8v4.5l-3 1.5V8z',
    gauge: 'M2.5 11.5a5.5 5.5 0 1 1 11 0M8 11.5l2.5-3.5M8 11.5h.01',
    inbound: 'M8 2.5v7M5 6.5l3 3 3-3M2.5 9.5v4h11v-4',
    info: 'M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM8 7.5v4M8 5h.01',
    link: 'M6.5 9.5l3-3M7 4.5 8.5 3a2.5 2.5 0 0 1 3.5 3.5L10.5 8M9 11.5 7.5 13A2.5 2.5 0 0 1 4 9.5L5.5 8',
    list: 'M2.5 4h.01M5.5 4h8M2.5 8h.01M5.5 8h8M2.5 12h.01M5.5 12h8',
    offline:
      'M2 2l12 12M6.2 6.2A5 5 0 0 0 4.5 7.5M8 4a7 7 0 0 1 6 3.1M2 7.1a7 7 0 0 1 1.9-1.7M10 9.9a3 3 0 0 0-4 .2M8 13h.01',
    plug: 'M6 2.5v3M10 2.5v3M4.5 5.5h7V8a3.5 3.5 0 0 1-7 0zM8 11.5v2',
    refresh: 'M13.5 8A5.5 5.5 0 1 1 11.9 4.1M13.5 2.5v3h-3',
    route:
      'M4 11.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM12 5.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM12 13.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM5.5 10h1c2 0 2-6 4-6M5.5 10h1c2 0 2 2 4 2',
    search: 'M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM10.7 10.7 14 14',
    server: 'M2.5 2.5h11v4.5h-11zM2.5 9h11v4.5h-11zM5 4.75h.01M5 11.25h.01',
    split: 'M8 14V9L3.5 3.5M8 9l4.5-5.5M7 3.5H3.5V7M9 3.5h3.5V7',
    tests: 'm2.5 4 1 1 2-2M7.5 4h6M2.5 8.5l1 1 2-2M7.5 8.5h6M2.5 13l1 1 2-2M7.5 13h6',
    trash: 'M2.5 4.5h11M6.5 4.5V2.5h3v2M4 4.5l.7 9h6.6l.7-9M6.7 7v4M9.3 7v4',
  } as const;

  export type IconName = keyof typeof PATHS;
</script>

<script lang="ts">
  interface Props {
    name: IconName;
    size?: number;
  }

  let { name, size = 16 }: Props = $props();
</script>

<svg
  class="icon"
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill="none"
  stroke="currentColor"
  stroke-width="1.5"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d={PATHS[name]} />
</svg>

<style>
  .icon {
    display: block;
  }
</style>
