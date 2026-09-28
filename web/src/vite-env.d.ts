/// <reference types="svelte" />
/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** WebSocket URL of the server; by default /ws next to the page. */
  readonly VITE_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
