import { describe, expect, it } from 'vitest';
import { isSearchComplete, readSearch, writeSearch } from './searchParams.js';

const read = (qs) => readSearch(new URLSearchParams(qs));

describe('search URL state', () => {
  it('round-trips a full search', () => {
    const qs = writeSearch({ fromId: '106', toId: '216', departure: '2026-11-11T08:00', sort: 'fastest', filters: { route: '72', maxDuration: 30, departFrom: '07:00', departTo: '' } });
    const s = read(qs);
    expect(s).toMatchObject({ fromId: '106', toId: '216', sort: 'fastest', filters: { route: '72', maxDuration: 30, departFrom: '07:00', departTo: '' }, problems: [] });
    expect(s.departure.value).toBe('2026-11-11T08:00');
    expect(isSearchComplete(s)).toBe(true);
  });
  it('omits defaults and empty values', () => {
    expect(writeSearch({ fromId: '1', toId: '2', departure: '2026-11-11T08:00', sort: 'earliest' })).toBe('from=1&to=2&departure=2026-11-11T08%3A00');
  });
  it('reports an invalid departure instead of silently replacing it', () => {
    const s = read('from=1&to=2&departure=2026-02-30T08:00');
    expect(s.departure).toBeNull();
    expect(s.problems.map((p) => p.field)).toContain('departure');
    expect(isSearchComplete(s)).toBe(false);
  });
  it('reports identical stops and unknown ordering, ignores garbage filters', () => {
    const s = read('from=5&to=5&departure=2026-11-11T08:00&sort=cheapest&maxDuration=abc&departFrom=25:00');
    expect(s.problems.map((p) => p.field).sort()).toEqual(['sort', 'to']);
    expect(s.sort).toBe('earliest');
    expect(s.filters.maxDuration).toBeNull();
    expect(s.filters.departFrom).toBe('');
    expect(isSearchComplete(s)).toBe(false);
  });
  it('treats missing params as an incomplete search', () => {
    expect(isSearchComplete(read(''))).toBe(false);
    expect(isSearchComplete(read('from=1'))).toBe(false);
  });
});
