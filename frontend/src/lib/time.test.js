import { describe, expect, it } from 'vitest';
import { addDays, clockOf, defaultDeparture, delhiNow, formatDuration, formatGtfsDate, minutesBetween, parseDeparture, parseGtfsTime } from './time.js';

describe('Delhi time', () => {
  it('computes "now" in Asia/Kolkata whatever the machine timezone is (UTC+5:30, across midnight)', () => {
    expect(delhiNow(new Date('2026-11-11T20:00:00Z'))).toEqual({ date: '2026-11-12', time: '01:30' });
    expect(delhiNow(new Date('2026-11-11T18:29:00Z'))).toEqual({ date: '2026-11-11', time: '23:59' });
    expect(defaultDeparture(new Date('2026-01-01T00:00:00Z'))).toBe('2026-01-01T05:30');
  });
  it('never defaults to a fixed historical date', () => {
    const year = Number(defaultDeparture().slice(0, 4));
    expect(year).toBeGreaterThanOrEqual(new Date().getUTCFullYear() - 0);
  });
});

describe('parseDeparture', () => {
  it('accepts minute and second precision and normalises to minutes', () => {
    expect(parseDeparture('2026-11-09T08:05')).toMatchObject({ ok: true, value: '2026-11-09T08:05', date: '2026-11-09', time: '08:05' });
    expect(parseDeparture('2026-11-09T08:05:30').value).toBe('2026-11-09T08:05');
  });
  it.each(['', null, 'tomorrow', '2026-13-01T08:00', '2026-02-30T08:00', '2026-11-09T24:00', '2026-11-09T08:60', '2026-11-09'])('rejects %s', (v) => {
    expect(parseDeparture(v).ok).toBe(false);
  });
});

describe('GTFS time', () => {
  it('maps service-day hours >= 24 to the next calendar day', () => {
    expect(parseGtfsTime('24:03:50')).toEqual({ clock: '00:03', dayOffset: 1, seconds: 86_630 });
    expect(parseGtfsTime('07:06:42').dayOffset).toBe(0);
    expect(parseGtfsTime('garbage')).toBeNull();
  });
  it('formats without applying the browser timezone', () => {
    expect(clockOf('2026-11-11T06:56:26')).toBe('06:56');
    expect(minutesBetween('2026-11-11T06:56:26', '2026-11-11T07:06:42')).toBe(10);
    expect(minutesBetween('2026-11-11T23:50:00', '2026-11-12T00:10:00')).toBe(20);
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(formatGtfsDate('20250101')).toMatch(/1 Jan,? 2025/);
    expect(formatDuration(5)).toBe('5 min');
    expect(formatDuration(65)).toBe('1 h 5 min');
    expect(formatDuration(120)).toBe('2 h');
  });
});
