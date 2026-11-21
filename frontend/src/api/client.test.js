import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet } from './client.js';
import { fetchHealth } from './endpoints.js';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const BASE = 'http://api.test/api/v1';

afterEach(() => vi.unstubAllGlobals());

describe('apiGet', () => {
  it('builds the URL from the base, encodes params, skips null values', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(apiGet('/stops', { q: 'a b&c', limit: null }, { baseUrl: BASE })).resolves.toEqual({ ok: true });
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/stops?q=a+b%26c`);
  });

  it('maps connection failures to kind=network', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(apiGet('/x', {}, { baseUrl: BASE })).rejects.toMatchObject({ kind: 'network' });
  });

  it('uses the structured error message and code from the backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ error: { code: 'stop_not_found', message: 'Unknown stop' }, detail: 'Unknown stop' }, 404)));
    await expect(apiGet('/x', {}, { baseUrl: BASE })).rejects.toMatchObject({ kind: 'http', status: 404, code: 'stop_not_found', message: 'Unknown stop' });
  });

  it('falls back to legacy detail strings and generic messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({ detail: 'old style' }, 400)).mockResolvedValueOnce(new Response('<html>', { status: 502 })));
    await expect(apiGet('/x', {}, { baseUrl: BASE })).rejects.toMatchObject({ message: 'old style' });
    await expect(apiGet('/x', {}, { baseUrl: BASE })).rejects.toMatchObject({ kind: 'http', message: 'Request failed (HTTP 502).' });
  });

  it('flags unreadable success bodies as parse errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not json', { status: 200 })));
    await expect(apiGet('/x', {}, { baseUrl: BASE })).rejects.toMatchObject({ kind: 'parse' });
  });

  it('times out', async () => {
    vi.stubGlobal('fetch', vi.fn((_u, { signal }) => new Promise((_r, reject) => signal.addEventListener('abort', () => reject(new DOMException('x', 'AbortError'))))));
    await expect(apiGet('/x', {}, { baseUrl: BASE, timeoutMs: 20 })).rejects.toMatchObject({ kind: 'timeout' });
  });

  it('reports caller aborts as kind=aborted', async () => {
    vi.stubGlobal('fetch', vi.fn((_u, { signal }) => new Promise((_r, reject) => signal.addEventListener('abort', () => reject(new DOMException('x', 'AbortError'))))));
    const c = new AbortController();
    const p = apiGet('/x', {}, { baseUrl: BASE, signal: c.signal });
    c.abort();
    await expect(p).rejects.toMatchObject({ kind: 'aborted' });
  });
});

describe('fetchHealth', () => {
  it('returns the structured body of a 503 so the UI can explain it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ status: 'needs_setup' }, 503)));
    await expect(fetchHealth({ baseUrl: BASE })).resolves.toEqual({ status: 'needs_setup' });
  });
  it('still throws when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('x')));
    await expect(fetchHealth({ baseUrl: BASE })).rejects.toBeInstanceOf(ApiError);
  });
});

describe('apiGet retries', () => {
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  const fail = (status) => ({ ok: false, status, json: async () => ({ error: { code: 'x', message: `HTTP ${status}` } }) });
  it('retries transient failures (network, 503) when asked, and then succeeds', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError('boom')).mockResolvedValueOnce(fail(503)).mockResolvedValueOnce(ok({ fine: true }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(apiGet('/x', {}, { baseUrl: 'http://api', retries: 2 })).resolves.toEqual({ fine: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
  it('never retries validation errors or 404s, and does not retry unless asked', async () => {
    const f404 = vi.fn().mockResolvedValue(fail(404));
    vi.stubGlobal('fetch', f404);
    await expect(apiGet('/x', {}, { baseUrl: 'http://api', retries: 3 })).rejects.toMatchObject({ status: 404 });
    expect(f404).toHaveBeenCalledTimes(1);
    const f503 = vi.fn().mockResolvedValue(fail(503));
    vi.stubGlobal('fetch', f503);
    await expect(apiGet('/x', {}, { baseUrl: 'http://api' })).rejects.toMatchObject({ status: 503 });
    expect(f503).toHaveBeenCalledTimes(1);
  });
  it('gives up after the allowed retries', async () => {
    const f = vi.fn().mockResolvedValue(fail(503));
    vi.stubGlobal('fetch', f);
    await expect(apiGet('/x', {}, { baseUrl: 'http://api', retries: 1 })).rejects.toMatchObject({ status: 503 });
    expect(f).toHaveBeenCalledTimes(2);
  });
});
