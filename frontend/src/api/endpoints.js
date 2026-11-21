// Every backend call the UI makes is defined here. Pages and components never build URLs or call fetch themselves.
import { apiGet, ApiError } from './client.js';
import { cached } from './cache.js';

const enc = encodeURIComponent;

/** Readiness. A 503 still carries a structured body ("needs_setup" / "error"); return it. */
export async function fetchHealth(options) {
  try {
    return await apiGet('/health', {}, options);
  } catch (err) {
    if (err instanceof ApiError && err.kind === 'http' && err.body?.status) return err.body;
    throw err;
  }
}

export const searchStops = ({ q, limit = 20, offset = 0, routeId } = {}, options) =>
  apiGet('/stops', { q, limit, offset, route_id: routeId }, options);

export const getStop = (stopId) => cached(`stop:${stopId}`, () => apiGet(`/stops/${enc(stopId)}`, {}, { retries: 1 }));

export const getStopDepartures = (stopId, { date, after, limit = 20 } = {}, options) =>
  apiGet(`/stops/${enc(stopId)}/departures`, { date, after, limit }, { retries: 1, ...options });

export const listRoutes = ({ q, agencyId, limit = 20, offset = 0 } = {}, options) =>
  apiGet('/routes', { q, agency_id: agencyId, limit, offset }, options);

export const getRoute = (routeId, options) => apiGet(`/routes/${enc(routeId)}`, {}, { retries: 1, ...options });

export const listRouteTrips = (routeId, { limit = 20, offset = 0 } = {}, options) =>
  apiGet(`/routes/${enc(routeId)}/trips`, { limit, offset }, options);

export const getTrip = (tripId, options) => apiGet(`/trips/${enc(tripId)}`, {}, { retries: 1, ...options });

export const getTripStopTimes = (tripId, { limit = 100, offset = 0 } = {}, options) =>
  apiGet(`/trips/${enc(tripId)}/stop-times`, { limit, offset }, options);

const STOP_TIMES_PAGE = 500; // the API maximum

/** All stop times of one trip (a single trip, so bounded: typically tens of rows), fetched page by page. */
export async function getAllTripStopTimes(tripId, options) {
  const items = [];
  for (let offset = 0; ; offset += STOP_TIMES_PAGE) {
    const page = await getTripStopTimes(tripId, { limit: STOP_TIMES_PAGE, offset }, { retries: 1, ...options });
    items.push(...page.items);
    if (items.length >= page.total || page.items.length === 0) return { trip_id: tripId, items, total: page.total };
  }
}

export const listAgencies = () => cached('agencies', () => apiGet('/agencies', {}, { retries: 1 }));
export const getSummary = () => cached('summary', () => apiGet('/gtfs/summary', {}, { retries: 1 }));
export const getValidationReport = () => cached('validation', () => apiGet('/gtfs/validation-report', {}, { retries: 1 }));

export const getActiveServices = ({ date, includeInactive = true } = {}, options) =>
  apiGet('/services/active', { date, include_inactive: includeInactive ? 'true' : undefined }, { retries: 1, ...options });

/** The routing engine. `limit` is the number of earliest departures at/after `departure` the server returns. */
export const searchJourneys = ({ fromId, toId, departure, limit = 30 }, options) =>
  apiGet('/journeys', { origin_stop_id: fromId, destination_stop_id: toId, departure, limit }, { retries: 1, ...options });

// --- Phase 4: geometry, nearby, clusters, smart search ---------------------------------------------------------------

/**
 * The real GTFS shape between two stops of a trip (backend slices + simplifies it). Never passes `fallback=stops`:
 * the straight stop-to-stop polyline is not a bus path and the UI must not draw it.
 */
export const getLegShape = ({ tripId, fromId, toId, board, toleranceM }, options) =>
  apiGet(`/trips/${enc(tripId)}/shape`, { from_stop_id: fromId, to_stop_id: toId, board, tolerance_m: toleranceM }, { retries: 1, ...options });

/** Simplified GTFS geometry of every shape of a route. */
export const getRouteShapeGeometry = (routeId, { toleranceM, maxPoints } = {}, options) =>
  apiGet(`/routes/${enc(routeId)}/shapes`, { geometry: 'true', tolerance_m: toleranceM, max_points: maxPoints }, { retries: 1, ...options });

/**
 * Stops near a point. PRIVACY: the coordinates are sent only to our own backend, never cached (cache keys would
 * hold them), never retried-with-logging, and never placed in the URL of the page.
 */
export const getNearbyStops = ({ lat, lon, radiusM = 500, limit = 20 }, options) =>
  apiGet('/stops/nearby', { lat, lon, radius_m: radiusM, limit }, options);

/** Place cluster (immutable reference data -> cached by id; the id is a hash of member stop ids, no coordinates). */
export const getCluster = (clusterId) => cached(`cluster:${clusterId}`, () => apiGet(`/clusters/${enc(clusterId)}`, {}, { retries: 1 }));

/** Ranked, typo-tolerant search grouped by place cluster. */
export const smartSearchStops = ({ q, limit = 8 }, options) => apiGet('/stops', { q, mode: 'smart', limit }, options);
