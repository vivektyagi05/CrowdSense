// The single place the API location is defined. Components never build URLs themselves.
export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000/api/v1';

/** Validate and normalise a base URL (absolute http(s) URL or same-origin path). */
export function resolveApiBaseUrl(value) {
  const raw = (value ?? '').trim();
  if (!raw) return DEFAULT_API_BASE_URL;
  if (raw.startsWith('/')) return raw.replace(/\/+$/, '');
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`VITE_API_BASE_URL must be an absolute http(s) URL or a path starting with "/": ${raw}`);
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(`VITE_API_BASE_URL must use http or https: ${raw}`);
  }
  return raw.replace(/\/+$/, '');
}

export const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
export const REQUEST_TIMEOUT_MS = 15000;

/**
 * Basemap style (Phase 4). Deliberately has NO default tile provider: the public OpenStreetMap tile servers must not be
 * used for an app like this (see docs/phase4/DECISIONS.md ADR-02). Without it the map still draws the real route and
 * stops on a plain background and says so. A key inside this URL is visible to every visitor: restrict it by domain.
 */
export function resolveMapStyleUrl(value) {
  const raw = (value ?? '').trim();
  if (!raw) return '';
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`VITE_MAP_STYLE_URL must be an absolute https URL to a MapLibre style JSON: ${raw}`);
  }
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname))) {
    throw new Error(`VITE_MAP_STYLE_URL must use https (http only for localhost): ${raw}`);
  }
  return raw;
}

export const MAP_STYLE_URL = resolveMapStyleUrl(import.meta.env.VITE_MAP_STYLE_URL);
