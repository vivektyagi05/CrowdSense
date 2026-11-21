import { describe, expect, it } from 'vitest';
import { applyFilters, availableSorts, durationSteps, journeyDetailPath, journeyFromLegs, normalizeJourneys, routesIn, sortJourneys, TRANSFER_PENALTY_MIN } from './journeys.js';
import journeysFixture from '../test/fixtures/journeys-106-216.json';

const leg = (tripId, routeId, dep, arr, extra = {}) => ({
  tripId, routeId, routeName: routeId, from: { id: 'A', name: 'A' }, to: { id: 'B', name: 'B' },
  departure: `2026-11-11T${dep}:00`, arrival: `2026-11-11T${arr}:00`, intermediateStops: 3, ...extra,
});

describe('normalizeJourneys (real API response)', () => {
  const journeys = normalizeJourneys(journeysFixture, { fromId: '106', toId: '216', date: '2026-11-11' });
  it('turns every direct item into a one-leg, zero-transfer journey carrying the API values', () => {
    expect(journeys).toHaveLength(30);
    const j = journeys[0];
    expect(j.transfers).toBe(0);
    expect(j.legs).toHaveLength(1);
    expect(j.legs[0]).toMatchObject({ tripId: '72_06_40', routeName: '114UP', from: { id: '106' }, to: { id: '216' }, intermediateStops: 7 });
    expect(j.durationMinutes).toBe(10);
    expect(j.waitingMinutes).toBe(0);
    expect(j.crowd.status).toBe('NOT_AVAILABLE');
  });
  it('builds a stable detail URL carrying trip, stops, service date and scheduled boarding time', () => {
    const url = journeyDetailPath(journeys[0], { fromId: '106', toId: '216', date: '2026-11-11' });
    expect(url).toBe('/journeys/72_06_40?from=106&to=216&date=2026-11-11&board=06%3A56%3A26');
  });
});

describe('multi-leg journeys', () => {
  it('computes transfers, waiting time and total duration from the legs', () => {
    const j = journeyFromLegs([leg('t1', '10', '08:00', '08:20'), leg('t2', '20', '08:35', '09:05')]);
    expect(j.transfers).toBe(1);
    expect(j.waits).toEqual([15]);
    expect(j.waitingMinutes).toBe(15);
    expect(j.durationMinutes).toBe(65);
    expect(j.stopsBetween).toBe(6);
  });
});

describe('sorting', () => {
  const direct = journeyFromLegs([leg('d', '1', '08:00', '08:50')]);
  const quick = journeyFromLegs([leg('q1', '2', '08:05', '08:20'), leg('q2', '3', '08:30', '08:45')]); // 40 min, 1 transfer
  const slow = journeyFromLegs([leg('s', '4', '07:50', '09:30')]); // 100 min, direct
  const all = [direct, quick, slow];
  it('orders by departure, duration, arrival, transfers and a balanced score', () => {
    expect(sortJourneys(all, 'earliest').map((j) => j.id)).toEqual([slow.id, direct.id, quick.id]);
    expect(sortJourneys(all, 'fastest')[0]).toBe(quick);
    expect(sortJourneys(all, 'arrival')[0]).toBe(quick);
    expect(sortJourneys(all, 'transfers').at(-1)).toBe(quick);
    expect(sortJourneys(all, 'balanced')[0]).toBe(direct); // 50 min direct beats 40 min + 12 min transfer penalty = 52
  });
  it('balanced weighs a transfer as TRANSFER_PENALTY_MIN minutes', () => {
    expect(TRANSFER_PENALTY_MIN).toBe(12);
    const near = journeyFromLegs([leg('n1', '5', '08:00', '08:20'), leg('n2', '6', '08:25', '08:50')]); // 50 + 12 = 62
    expect(sortJourneys([near, direct], 'balanced')[0]).toBe(direct); // 50 < 62
  });
  it('does not mutate its input and is stable on ties', () => {
    const copy = [...all];
    sortJourneys(all, 'fastest');
    expect(all).toEqual(copy);
    const a = journeyFromLegs([leg('a', '1', '08:00', '08:10')]);
    const b = journeyFromLegs([leg('b', '1', '08:00', '08:10')]);
    expect(sortJourneys([b, a], 'fastest').map((j) => j.legs[0].tripId)).toEqual(['a', 'b']);
  });
  it('only offers orderings that can reorder the result set', () => {
    expect(availableSorts([direct, slow]).map((s) => s.value)).toEqual(['earliest', 'fastest', 'arrival']);
    expect(availableSorts(all).map((s) => s.value)).toContain('transfers');
    expect(availableSorts(all).map((s) => s.value)).toContain('balanced');
  });
});

describe('filters', () => {
  const j1 = journeyFromLegs([leg('a', '10', '06:00', '06:20')]);
  const j2 = journeyFromLegs([leg('b', '20', '09:00', '10:00')]);
  const none = { route: '', maxDuration: null, departFrom: '', departTo: '' };
  it('filters by route, duration and departure window', () => {
    expect(applyFilters([j1, j2], { ...none, route: '20' })).toEqual([j2]);
    expect(applyFilters([j1, j2], { ...none, maxDuration: 30 })).toEqual([j1]);
    expect(applyFilters([j1, j2], { ...none, departFrom: '08:00' })).toEqual([j2]);
    expect(applyFilters([j1, j2], { ...none, departTo: '07:00' })).toEqual([j1]);
    expect(applyFilters([j1, j2], none)).toHaveLength(2);
  });
  it('offers only route and duration choices that exist in the result set', () => {
    expect(routesIn([j1, j2]).map((r) => r.id)).toEqual(['10', '20']);
    expect(durationSteps([j1, j2])).toEqual([15, 30, 45]);
    expect(durationSteps([])).toEqual([]);
  });
});
