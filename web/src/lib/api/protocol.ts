// Messages and models of server/PROTOCOL.md.

/** A known string value, or a newer one the client shows as is. */
type Open<T extends string> = T | (string & {});

export type TestRule = Open<
  | 'status_204'
  | 'status_2xx'
  | 'status_below_400'
  | 'status_below_500'
  | 'status_below_503'
  | 'any_status'
>;

export interface OutboundTest {
  url: string;
  /** Unique, non-empty; the key in OutboundServer.tests. */
  alias: string;
  rule: TestRule;
}

export interface ServerSettings {
  id: 0;
  /** Seconds, greater than 0. */
  subscription_refresh_interval: number;
  /** ISO 8601 UTC time of the last successful refresh. */
  last_subscription_refresh: string | null;
  outbound_tests: OutboundTest[];
}

export interface SubscriptionLink {
  id: string;
  /** Scheme and host only; the full link is secret. */
  url_short: string;
}

export interface OutboundServer {
  id: string;
  name: string;
  address: string;
  port: number;
  protocol: Open<'vless' | 'shadowsocks' | 'hysteria'>;
  subscription_id: string | null;
  source_tag: string | null;
  transport: Open<'tcp' | 'grpc' | 'ws' | 'xhttp' | 'hysteria'>;
  security: Open<'none' | 'tls' | 'reality'>;
  server_name: string | null;
  fingerprint: string | null;
  alpn: string[];
  public_key: string | null;
  short_id: string | null;
  spider_x: string | null;
  allow_insecure: boolean | null;
  host: string | null;
  path: string | null;
  service_name: string | null;
  grpc_mode: string | null;
  xhttp_mode: string | null;
  vless_flow: string | null;
  shadowsocks_method: string | null;
  shadowsocks_udp_over_tcp: boolean | null;
  shadowsocks_uot_version: number | null;
  hysteria_version: number | null;
  /** Best TCP connect time in ms; null when not checked, not answering or not TCP. */
  ping: number | null;
  /** Download speed in bytes per second; 0 when the download failed. */
  speed: number | null;
  /** 0–100; null when not checked. */
  rating: number | null;
  /** Test alias → passed; null when not checked. May keep aliases of removed tests. */
  tests: Record<string, boolean> | null;
  is_connected: boolean;
}

export type TaskId = Open<'refresh_subscriptions' | 'test_outbound_servers'>;

export interface Task {
  id: TaskId;
  status: Open<'running' | 'stopped'>;
}

export interface Models {
  server_settings: ServerSettings;
  subscription_link: SubscriptionLink;
  outbound_server: OutboundServer;
  task: Task;
}

export type ModelName = keyof Models;

export const MODEL_NAMES: readonly ModelName[] = [
  'server_settings',
  'subscription_link',
  'outbound_server',
  'task',
];

export interface SubscriptionMessage<M extends ModelName = ModelName> {
  type: 'subscription';
  model: M;
  /** true: a full snapshot that replaces the collection; false: changes only. */
  refresh: boolean;
  payload: Models[M][];
  deleted_ids: Models[M]['id'][];
}

export type ErrorCode = Open<
  | 'bad_request'
  | 'unknown_request'
  | 'validation_error'
  | 'not_found'
  | 'conflict'
  | 'subscription_error'
  | 'core_error'
  | 'cancelled'
  | 'internal_error'
>;

export interface ResponseError {
  code: ErrorCode;
  /** English text for logs; not meant for users. */
  message: string;
  details: Record<string, unknown>;
}

export interface ResponseMessage {
  type: 'response';
  model: string | null;
  request_id: string | null;
  ok: boolean;
  payload: Record<string, unknown>;
  error?: ResponseError;
}

export type ServerMessage = SubscriptionMessage | ResponseMessage;

type Empty = Record<string, never>;

/** Every request the server accepts, keyed by "type/model". */
export interface Requests {
  'add/subscription_link': { payload: { url: string }; result: { id: string } };
  'change/subscription_link': { payload: { id: string; url?: string }; result: Empty };
  'delete/subscription_link': { payload: { id: string }; result: Empty };
  'change/server_settings': {
    payload: { id: 0; subscription_refresh_interval?: number; outbound_tests?: OutboundTest[] };
    result: Empty;
  };
  'request/refresh_subscriptions': { payload: Empty; result: Empty };
  'request/test_outbound_servers': { payload: Empty; result: Empty };
  'request/connect_outbound_server': { payload: { id: string }; result: Empty };
}

export type RequestKey = keyof Requests;
export type RequestPayload<K extends RequestKey> = Requests[K]['payload'];
export type RequestResult<K extends RequestKey> = Requests[K]['result'];
