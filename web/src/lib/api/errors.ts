import type { ErrorCode, ResponseError } from './protocol';

/** Client-side codes next to the server's ErrorCode. */
export type ClientErrorCode = 'disconnected';

/** A failed request: an error response from the server or a lost connection. */
export class RequestError extends Error {
  readonly code: ErrorCode | ClientErrorCode;
  readonly details: Record<string, unknown>;

  constructor(code: ErrorCode | ClientErrorCode, message: string, details = {}) {
    super(message);
    this.name = 'RequestError';
    this.code = code;
    this.details = details;
  }

  static fromResponse(error: ResponseError): RequestError {
    return new RequestError(error.code, error.message, error.details ?? {});
  }

  /** details.field, when the server named the field at fault. */
  get field(): string | undefined {
    const field = this.details.field;
    return typeof field === 'string' ? field : undefined;
  }
}

const DEFAULT_TEXT: Record<string, string> = {
  disconnected: 'Lost connection to the server. Check the result after it reconnects.',
  bad_request: 'The server rejected the request as malformed.',
  unknown_request: 'The server does not support this action.',
  validation_error: 'Some values are not valid.',
  not_found: 'It no longer exists on the server.',
  conflict: 'This conflicts with the current state of the server.',
  subscription_error: 'A subscription failed to load. Servers were left unchanged.',
  core_error: 'The proxy core could not do this. See the server log for details.',
  cancelled: 'The task was stopped before it finished.',
  internal_error: 'Unexpected server error. See the server log for details.',
};

/**
 * User-facing text for a failed request. `overrides` gives texts for codes
 * whose meaning depends on the action, e.g. { conflict: 'Already added.' }.
 */
export function describeError(
  error: unknown,
  overrides: Partial<Record<string, string>> = {},
): string {
  if (error instanceof RequestError) {
    return overrides[error.code] ?? DEFAULT_TEXT[error.code] ?? `Request failed (${error.code}).`;
  }
  console.error(error);
  return 'Something went wrong in the page. See the browser console.';
}
