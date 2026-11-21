import { describe, expect, it } from 'vitest';
import { API_BASE_URL, DEFAULT_API_BASE_URL, resolveApiBaseUrl } from './config.js';

describe('resolveApiBaseUrl', () => {
  it('falls back to the local default when unset or blank', () => {
    expect(resolveApiBaseUrl(undefined)).toBe(DEFAULT_API_BASE_URL);
    expect(resolveApiBaseUrl('   ')).toBe(DEFAULT_API_BASE_URL);
  });
  it('accepts absolute http(s) URLs and trims trailing slashes', () => {
    expect(resolveApiBaseUrl('https://api.example.org/api/v1/')).toBe('https://api.example.org/api/v1');
  });
  it('accepts same-origin paths', () => {
    expect(resolveApiBaseUrl('/api/v1/')).toBe('/api/v1');
  });
  it('rejects invalid values loudly', () => {
    expect(() => resolveApiBaseUrl('localhost:8000')).toThrow(/VITE_API_BASE_URL/);
    expect(() => resolveApiBaseUrl('ftp://x.test')).toThrow(/http/);
  });
  it('exports a resolved base URL', () => {
    expect(API_BASE_URL).toMatch(/\/api\/v1$/);
  });
});
