import type { OutboundServer } from './api/protocol';
import type { ConnectionStatus } from './api/status';

/**
 * State of the proxy connection:
 * - none: no server is connected;
 * - working: traffic goes through a server;
 * - failed: an error, and there is no working connection.
 *
 * Plain functions without stores: the desktop application shows the same state
 * in its tray icon.
 */
export type LinkState = 'none' | 'working' | 'failed';

/**
 * status: the connection to the x-proxy-router server; server: the connected
 * one; lost: the connected server was removed or can no longer be used.
 */
export function linkState(
  status: ConnectionStatus,
  server: Pick<OutboundServer, 'rating'> | null,
  lost: boolean,
): LinkState {
  // Without the x-proxy-router server nothing can be known to work.
  if (status === 'offline') return 'failed';
  // Rating 0: the last check found the server unavailable or failing every test.
  // An unchecked server counts as working: the core switched to it.
  if (server) return server.rating === 0 ? 'failed' : 'working';
  return lost ? 'failed' : 'none';
}

/** Why the state is what it is, for tooltips and screen readers. */
export function linkDescription(
  status: ConnectionStatus,
  server: Pick<OutboundServer, 'name' | 'rating'> | null,
  lost: boolean,
): string {
  if (status === 'offline') return 'No connection to the x-proxy-router server';
  if (server && server.rating === 0) return `${server.name} failed its last check`;
  if (server) return `Traffic goes through ${server.name}`;
  if (lost) return 'The connected server was removed or can no longer be used';
  return 'No server is connected';
}
