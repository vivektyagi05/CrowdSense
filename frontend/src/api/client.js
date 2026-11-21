import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '../config.js';

/**
 * kind: 'network' (backend unreachable) | 'timeout' | 'aborted' | 'http' | 'parse'
 */
export class ApiError extends Error {
  constructor(message, { kind, status = null, code = null, body = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function errorMessage(body, status) {
  if (body && typeof body === 'object') {
    if (body.error && typeof body.error.message === 'string') return body.error.message;
    if (typeof body.detail === 'string') return body.detail;
  }
  return `Request failed (HTTP ${status}).`;
}

/** GET `${baseUrl}${path}?params` and return parsed JSON, or throw ApiError. */
const RETRYABLE_STATUS = new Set([502, 503, 504]);
const RETRY_DELAY_MS = 300;

/**
 * GET with an opt-in retry for *transient* failures only (network, timeout, 502/503/504). Validation errors,
 * 404s and caller cancellations are never retried. Reads are idempotent, so a retry is safe.
 */
export async function apiGet(path, params = {}, options = {}) {
  const { retries = 0, signal } = options;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await apiGetOnce(path, params, options);
    } catch (err) {
      const transient = err instanceof ApiError && (err.kind === 'network' || err.kind === 'timeout' || (err.kind === 'http' && RETRYABLE_STATUS.has(err.status)));
      if (!transient || attempt >= retries || signal?.aborted) throw err;
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS * (attempt + 1)));
    }
  }
}

async function apiGetOnce(path, params = {}, { signal, timeoutMs = REQUEST_TIMEOUT_MS, baseUrl = API_BASE_URL } = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }
  const qs = query.toString();
  const url = `${baseUrl}${path}${qs ? `?${qs}` : ''}`;

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }

  try {
    let response;
    try {
      response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
    } catch (err) {
      if (timedOut) throw new ApiError('The backend took too long to respond.', { kind: 'timeout' });
      if (signal?.aborted || err?.name === 'AbortError') throw new ApiError('Request cancelled.', { kind: 'aborted' });
      throw new ApiError('Cannot reach the CrowdSense backend.', { kind: 'network' });
    }

    let body = null;
    try {
      body = await response.json();
    } catch {
      if (response.ok) throw new ApiError('The backend returned an unreadable response.', { kind: 'parse', status: response.status });
    }
    if (!response.ok) {
      throw new ApiError(errorMessage(body, response.status), {
        kind: 'http',
        status: response.status,
        code: body?.error?.code ?? null,
        body,
      });
    }
    return body;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
