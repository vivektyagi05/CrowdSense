import { describe, expect, it } from 'vitest';
import { buildLeg } from './journeyDetail.js';
import stoptimes from '../test/fixtures/stoptimes-72.json';
import trip from '../test/fixtures/trip-72.json';

describe('buildLeg (real trip 72_06_40)', () => {
  it('cuts the passenger leg between the boarding and alighting stops', () => {
    const { leg } = buildLeg({ stopTimes: stoptimes.items, trip, fromId: '106', toId: '216', board: '06:56:26' });
    expect(leg.routeName).toBe('114UP');
    expect(leg.stops[0]).toMatchObject({ id: '106', time: '06:56' });
    expect(leg.stops.at(-1)).toMatchObject({ id: '216', time: '07:06' });
    expect(leg.stops).toHaveLength(9); // board + 7 intermediate + alight (matches the search's intermediate_stops = 7)
    expect(leg.durationMinutes).toBe(10);
    expect(leg.stops.map((s) => s.sequence)).toEqual([...leg.stops.map((s) => s.sequence)].sort((a, b) => a - b));
  });
  it('reports why a leg cannot be built', () => {
    expect(buildLeg({ stopTimes: stoptimes.items, trip, fromId: 'nope', toId: '216', board: '06:56:26' }).error).toBe('origin_not_on_trip');
    expect(buildLeg({ stopTimes: stoptimes.items, trip, fromId: '216', toId: '106', board: '07:06:42' }).error).toBe('destination_not_after_origin');
  });
  it('uses the scheduled boarding time to pick the right call on a loop route, and handles post-midnight times', () => {
    const calls = [
      { stop_id: 'A', stop_name: 'A', stop_sequence: 1, arrival_time: '23:00:00', departure_time: '23:00:00' },
      { stop_id: 'B', stop_name: 'B', stop_sequence: 2, arrival_time: '23:30:00', departure_time: '23:30:00' },
      { stop_id: 'A', stop_name: 'A', stop_sequence: 3, arrival_time: '23:50:00', departure_time: '23:55:00' },
      { stop_id: 'B', stop_name: 'B', stop_sequence: 4, arrival_time: '24:20:00', departure_time: '24:20:00' },
    ];
    const { leg } = buildLeg({ stopTimes: calls, trip: { trip_id: 'L', route_id: 'R', route_short_name: 'R1' }, fromId: 'A', toId: 'B', board: '23:55:00' });
    expect(leg.stops.map((s) => s.sequence)).toEqual([3, 4]);
    expect(leg.stops[1]).toMatchObject({ time: '00:20', dayOffset: 1 });
    expect(leg.durationMinutes).toBe(25);
  });
});
