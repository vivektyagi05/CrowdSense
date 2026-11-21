import { parseGtfsTime } from './time.js';

/**
 * Cut one passenger leg out of a trip's full stop-time list.
 *
 * Boarding is the stop_time at `fromId` whose departure equals the scheduled boarding time the search returned
 * (`board`, HH:MM:SS) - this disambiguates loop routes that call at the same stop twice - falling back to the first
 * call at that stop. Alighting is the first later call at `toId`. Returns {leg} or {error: code}.
 */
export function buildLeg({ stopTimes, trip, fromId, toId, board }) {
  const calls = stopTimes;
  let boardIdx = calls.findIndex((s) => s.stop_id === fromId && s.departure_time === board);
  if (boardIdx < 0) boardIdx = calls.findIndex((s) => s.stop_id === fromId && s.departure_time);
  if (boardIdx < 0) return { error: 'origin_not_on_trip' };
  const alightIdx = calls.findIndex((s, i) => i > boardIdx && s.stop_id === toId && (s.arrival_time || s.departure_time));
  if (alightIdx < 0) return { error: 'destination_not_after_origin' };

  const slice = calls.slice(boardIdx, alightIdx + 1);
  const stops = slice.map((s, i) => {
    const raw = i === 0 ? s.departure_time : s.arrival_time || s.departure_time;
    const t = parseGtfsTime(raw);
    return { id: s.stop_id, name: s.stop_name, lat: s.stop_lat, lon: s.stop_lon, sequence: s.stop_sequence, time: t?.clock ?? '', dayOffset: t?.dayOffset ?? 0, seconds: t?.seconds ?? null };
  });
  const first = stops[0];
  const last = stops[stops.length - 1];
  const durationMinutes = first.seconds != null && last.seconds != null ? Math.round((last.seconds - first.seconds) / 60) : null;
  return {
    leg: {
      tripId: trip.trip_id,
      routeId: trip.route_id,
      routeName: trip.route_short_name || trip.route_long_name || trip.route_id,
      headsign: trip.trip_headsign || null,
      serviceId: trip.service_id,
      durationMinutes,
      stops,
    },
  };
}
