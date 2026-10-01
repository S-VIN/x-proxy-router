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

/** Added and deleted, never changed. It has no name: clients name it after its site. */
export interface OutboundTest {
  /** The key in OutboundServer.tests. */
  id: string;
  /** Unique among the tests. */
  url: string;
  rule: TestRule;
}

export interface ServerSettings {
  id: 0;
  /** Seconds, greater than 0. */
  subscription_refresh_interval: number;
  /** ISO 8601 UTC time of the last successful refresh. */
  last_subscription_refresh: string | null;
  /** The server chooses the connected server itself; a client's choice turns it off. */
  auto_connect: boolean;
}

export interface SubscriptionLink {
  id: string;
  /** Scheme and host only; the full link is secret. */
  url_short: string;
}

export interface RegFilter {
  id: string;
  /** A pattern (* is any characters) matched with the whole server name, ignoring case. */
  reg: string;
}

/** Why a server is filtered; by_reg_filter wins when there are several reasons. */
export type FilterReason = Open<'by_reg_filter' | 'by_ping' | 'by_subscription'>;

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
  /** Test id → passed; null when not checked. May keep ids of removed tests. */
  tests: Record<string, boolean> | null;
  /** Filtered servers cannot be connected; null when not filtered. */
  filtered: FilterReason | null;
  is_connected: boolean;
}

export type InboundType = Open<'proxy'>;

/** Where the core accepts traffic; fields prefixed with a type are null for other types. */
export interface InboundServer {
  id: string;
  /** Cannot change after the inbound is added. */
  type: InboundType;
  /** false: kept, but the core does not listen. */
  enabled: boolean;
  /** IP address; 0.0.0.0 or :: accept connections from the network. */
  proxy_listen: string | null;
  proxy_port: number | null;
  /** null: no authentication. The password is secret and never sent to clients. */
  proxy_username: string | null;
  /** Why the core does not listen; null while it listens or is disabled. */
  error: string | null;
}

/** Inbound fields a client sets; username and password are set or removed together. */
export interface InboundSettings {
  enabled?: boolean;
  proxy_listen?: string;
  proxy_port?: number;
  proxy_username?: string | null;
  proxy_password?: string | null;
}

/** proxy: through the connected server; direct: without a server; block: closed at once. */
export type RoutingAction = Open<'proxy' | 'direct' | 'block'>;

export interface RoutingRule {
  id: string;
  /** 1 is checked first; the rules are numbered 1..N without gaps. */
  priority: number;
  /** A pattern of a domain or an IP address, stored in lower case. */
  reg: string;
  action: RoutingAction;
}

export type TaskId = Open<'refresh_subscriptions' | 'test_outbound_servers'>;

export interface Task {
  id: TaskId;
  status: Open<'running' | 'stopped'>;
}

export interface Models {
  server_settings: ServerSettings;
  subscription_link: SubscriptionLink;
  reg_filter: RegFilter;
  outbound_test: OutboundTest;
  outbound_server: OutboundServer;
  inbound_server: InboundServer;
  routing_rule: RoutingRule;
  task: Task;
}

export type ModelName = keyof Models;

export const MODEL_NAMES: readonly ModelName[] = [
  'server_settings',
  'subscription_link',
  'reg_filter',
  'outbound_test',
  'outbound_server',
  'inbound_server',
  'routing_rule',
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
  'delete/subscription_link': { payload: { id: string }; result: Empty };
  'add/reg_filter': { payload: { reg: string }; result: { id: string } };
  'delete/reg_filter': { payload: { id: string }; result: Empty };
  'add/outbound_test': { payload: { url: string; rule: TestRule }; result: { id: string } };
  'delete/outbound_test': { payload: { id: string }; result: Empty };
  'add/inbound_server': {
    payload: { type: InboundType } & InboundSettings;
    result: { id: string };
  };
  'change/inbound_server': { payload: { id: string } & InboundSettings; result: Empty };
  'delete/inbound_server': { payload: { id: string }; result: Empty };
  'add/routing_rule': {
    payload: { reg: string; action: RoutingAction; priority?: number };
    result: { id: string };
  };
  'change/routing_rule': {
    payload: { id: string; priority?: number; reg?: string; action?: RoutingAction };
    result: Empty;
  };
  'delete/routing_rule': { payload: { id: string }; result: Empty };
  'change/server_settings': {
    payload: {
      id: 0;
      subscription_refresh_interval?: number;
      auto_connect?: boolean;
    };
    result: Empty;
  };
  'request/refresh_subscriptions': { payload: Empty; result: Empty };
  'request/test_outbound_servers': { payload: Empty; result: Empty };
  'request/connect_outbound_server': { payload: { id: string }; result: Empty };
}

export type RequestKey = keyof Requests;
export type RequestPayload<K extends RequestKey> = Requests[K]['payload'];
export type RequestResult<K extends RequestKey> = Requests[K]['result'];
