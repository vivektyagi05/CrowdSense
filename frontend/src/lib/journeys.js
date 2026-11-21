// View-model for journeys. The backend currently returns *direct* journeys (one bus, one leg); this module turns each
// into a multi-leg-capable structure so the UI never assumes there is exactly one leg. Nothing here invents data: every
// field comes from the API response or from the search the passenger entered.
import { clockOf, minutesBetween } from './time.js';

export function normalizeJourneys(response, search) {
  const items = response?.items ?? [];
  return items.map((item) => {
    const leg = {
      tripId: item.trip_id,
      routeId: item.route_id,
      routeName: item.route_name,
      from: { id: search.fromId, name: item.origin },
      to: { id: search.toId, name: item.destination },
      departure: item.departure,
      arrival: item.arrival,
      durationMinutes: item.scheduled_duration_minutes,
      intermediateStops: item.intermediate_stops,
    };
    return journeyFromLegs([leg], { crowd: item.crowd, dataBasis: item.data_basis });
  });
}

/** Build a journey from ordered legs. Waiting time is the gap between one leg's arrival and the next one's departure. */
export function journeyFromLegs(legs, extra = {}) {
  const waits = legs.slice(1).map((leg, i) => Math.max(0, minutesBetween(legs[i].arrival, leg.departure)));
  const first = legs[0];
  const last = legs[legs.length - 1];
  return {
    id: legs.map((l) => `${l.tripId}@${clockOf(l.departure)}`).join('+'),
    legs,
    waits,
    transfers: legs.length - 1,
    departure: first.departure,
    arrival: last.arrival,
    durationMinutes: minutesBetween(first.departure, last.arrival),
    waitingMinutes: waits.reduce((a, b) => a + b, 0),
    stopsBetween: legs.reduce((a, l) => a + (l.intermediateStops ?? 0), 0),
    ...extra,
  };
}

// "Balanced" trades time against hassle: each transfer costs as much as TRANSFER_PENALTY_MIN minutes of riding.
export const TRANSFER_PENALTY_MIN = 12;

const SORT_DEFS = {
  earliest: { label: 'Earliest departure', cmp: (a, b) => a.departure.localeCompare(b.departure) },
  fastest: { label: 'Fastest', cmp: (a, b) => a.durationMinutes - b.durationMinutes },
  arrival: { label: 'Earliest arrival', cmp: (a, b) => a.arrival.localeCompare(b.arrival) },
  transfers: { label: 'Fewest transfers', cmp: (a, b) => a.transfers - b.transfers },
  balanced: {
    label: 'Balanced',
    cmp: (a, b) => a.durationMinutes + a.transfers * TRANSFER_PENALTY_MIN - (b.durationMinutes + b.transfers * TRANSFER_PENALTY_MIN),
  },
};
export const DEFAULT_SORT = 'earliest';

/** Only offer orderings that can actually reorder this result set: "Fewest transfers" is a no-op when every journey is direct. */
export function availableSorts(journeys) {
  const transfersVary = new Set(journeys.map((j) => j.transfers)).size > 1;
  return Object.entries(SORT_DEFS)
    .filter(([key]) => transfersVary || (key !== 'transfers' && key !== 'balanced'))
    .map(([value, def]) => ({ value, label: def.label }));
}

export function isSortKey(value) {
  return Object.hasOwn(SORT_DEFS, value);
}

/** Stable sort: ties fall back to departure time, then trip id. */
export function sortJourneys(journeys, key) {
  const def = SORT_DEFS[key] ?? SORT_DEFS[DEFAULT_SORT];
  return [...journeys].sort((a, b) => def.cmp(a, b) || a.departure.localeCompare(b.departure) || a.id.localeCompare(b.id));
}

/** Filters run over the complete candidate set the server returned; they never change the server query. */
export function applyFilters(journeys, f) {
  return journeys.filter((j) => {
    if (f.route && !j.legs.some((l) => l.routeId === f.route)) return false;
    if (f.maxDuration != null && j.durationMinutes > f.maxDuration) return false;
    if (f.departFrom && clockOf(j.departure) < f.departFrom) return false;
    if (f.departTo && clockOf(j.departure) > f.departTo) return false;
    return true;
  });
}

export function hasActiveFilters(f) {
  return Boolean(f.route || f.maxDuration != null || f.departFrom || f.departTo);
}

/** Routes present in a result set, for the route filter: [{id, name, count}] ordered by name. */
export function routesIn(journeys) {
  const map = new Map();
  for (const j of journeys) {
    for (const l of j.legs) {
      const entry = map.get(l.routeId) ?? { id: l.routeId, name: l.routeName, count: 0 };
      entry.count += 1;
      map.set(l.routeId, entry);
    }
  }
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }));
}

/** Duration cut-offs worth offering for this result set (only values that would actually exclude something). */
export function durationSteps(journeys) {
  if (!journeys.length) return [];
  const max = Math.max(...journeys.map((j) => j.durationMinutes));
  return [15, 30, 45, 60, 90, 120].filter((s) => s < max);
}

/** Stable URL of a journey: trip + the passenger's stops + scheduled boarding time + the service date searched. */
export function journeyDetailPath(journey, search) {
  const leg = journey.legs[0];
  const q = new URLSearchParams({
    from: search.fromId, to: search.toId, date: search.date, board: leg.departure.slice(11, 19),
  });
  return `/journeys/${encodeURIComponent(leg.tripId)}?${q.toString()}`;
}
