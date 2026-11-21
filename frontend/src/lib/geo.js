// Map data boundary. These helpers only *reshape* real API data into what a map layer needs; they never invent
// geometry. In particular a straight line between stops is NOT a bus path: real route geometry comes only from the
// GTFS shape endpoints (`/trips/{id}/shape?from_stop_id&to_stop_id`, `/routes/{id}/shapes?geometry=true`). There is
// deliberately NO function in this file that builds a line from stops: `lineFeature` accepts only API coordinates.

/** [{id, name, lat, lon, sequence}] from API stop-time rows; rows without coordinates are skipped. */
export function toMapStops(stopTimes) {
  return stopTimes
    .filter((s) => Number.isFinite(s.stop_lat) && Number.isFinite(s.stop_lon))
    .map((s) => ({ id: s.stop_id, name: s.stop_name, lat: s.stop_lat, lon: s.stop_lon, sequence: s.stop_sequence }));
}

/** What a map needs to request geometry for a leg: the trip (shape lookup) and its boarding/alighting stops. */
export function legGeometryRef(leg) {
  return { tripId: leg.tripId, routeId: leg.routeId, boardStopId: leg.from.id, alightStopId: leg.to.id };
}

/** Transfer points of a journey: the stop where each leg ends and the next begins. */
export function transferPoints(journey) {
  return journey.legs.slice(1).map((leg, i) => ({ stopId: leg.from.id, name: leg.from.name, afterLegIndex: i }));
}

// --- Phase 4 map data (pure, unit-tested; the map engine itself lives behind features/map/mapAdapter.js) -----------

/** Delhi-NCR service area, identical to the backend's validation box (docs/phase4/DECISIONS.md ADR-02). */
export const NCR_BOX = { minLat: 28.0, maxLat: 29.5, minLon: 76.4, maxLon: 77.8 };
/** Centre of the box, used only as the initial view of a map that has nothing to show yet. */
export const NCR_CENTER = [77.1, 28.65];

export const isFiniteCoord = (lat, lon) => Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;

export function inServiceArea(lat, lon) {
  return isFiniteCoord(lat, lon) && lat >= NCR_BOX.minLat && lat <= NCR_BOX.maxLat && lon >= NCR_BOX.minLon && lon <= NCR_BOX.maxLon;
}

/** [[minLon, minLat], [maxLon, maxLat]] of [lon, lat] pairs, or null when there is nothing finite to bound. */
export function boundsOf(coords) {
  let minLon = Infinity; let minLat = Infinity; let maxLon = -Infinity; let maxLat = -Infinity;
  for (const c of coords ?? []) {
    if (!Array.isArray(c) || !isFiniteCoord(c[1], c[0])) continue;
    minLon = Math.min(minLon, c[0]); maxLon = Math.max(maxLon, c[0]);
    minLat = Math.min(minLat, c[1]); maxLat = Math.max(maxLat, c[1]);
  }
  return minLon === Infinity ? null : [[minLon, minLat], [maxLon, maxLat]];
}

/** GeoJSON LineString feature from API geometry. Returns null unless there are >= 2 real points: never a guess. */
export function lineFeature(coordinates, properties = {}) {
  const pts = (coordinates ?? []).filter((c) => Array.isArray(c) && isFiniteCoord(c[1], c[0]));
  return pts.length >= 2 ? { type: 'Feature', properties, geometry: { type: 'LineString', coordinates: pts } } : null;
}

const pointFeature = (id, lon, lat, properties) => ({ type: 'Feature', id, properties: { id, ...properties }, geometry: { type: 'Point', coordinates: [lon, lat] } });

/** FeatureCollection of stop points. `role`: 'board' | 'alight' | 'stop' (data-driven styling). Rows without coordinates are skipped. */
export function stopsFeatures(stops, { roles = {} } = {}) {
  return {
    type: 'FeatureCollection',
    features: (stops ?? []).filter((s) => isFiniteCoord(s.lat, s.lon)).map((s, i) => pointFeature(i, s.lon, s.lat, { stopId: s.id, name: s.name, sequence: s.sequence ?? null, role: roles[s.id] ?? 'stop' })),
  };
}

export const emptyCollection = () => ({ type: 'FeatureCollection', features: [] });

/** Honest wording for every non-ok geometry status. */
export const GEOMETRY_MESSAGES = {
  no_shape: 'Route path not published for this trip. The stops below are still correct.',
  unreliable_projection: 'Path could not be matched reliably to these stops, so no line is drawn. The stops below are still correct.',
  failed: 'The route path could not be loaded. The stops below are still correct.',
  not_requested: 'Route path is not available.',
};

/**
 * Everything a map needs for one journey leg, from the API's leg-shape response + the leg's stop list.
 * `line` is non-null ONLY when status === 'ok' and the API returned >= 2 coordinates.
 */
export function legMapData({ shape, stops, boardId, alightId }) {
  const status = shape?.status ?? 'failed';
  const ok = status === 'ok';
  const line = ok ? lineFeature(shape.coordinates, { source: 'gtfs_shape' }) : null;
  const roles = { [boardId]: 'board', [alightId]: 'alight' };
  const pts = (stops ?? []).filter((s) => isFiniteCoord(s.lat, s.lon));
  const features = stopsFeatures(pts, { roles });
  const bounds = boundsOf([...(line ? line.geometry.coordinates : []), ...pts.map((s) => [s.lon, s.lat])]);
  return { status: line ? 'ok' : (ok ? 'no_shape' : status), line, stops: features, bounds, message: line ? null : GEOMETRY_MESSAGES[ok ? 'no_shape' : status] ?? GEOMETRY_MESSAGES.failed };
}

/** Map data for a route page: one selected shape item (from `/routes/{id}/shapes?geometry=true`) + the ordered stops. */
export function routeMapData({ shapeItem, stops }) {
  const ok = shapeItem?.geometry_status === 'ok';
  const line = ok ? lineFeature(shapeItem.coordinates, { source: 'gtfs_shape' }) : null;
  const features = stopsFeatures(stops ?? []);
  return {
    status: line ? 'ok' : (shapeItem ? 'no_shape' : 'failed'), line, stops: features,
    bounds: boundsOf([...(line ? line.geometry.coordinates : []), ...(stops ?? []).filter((s) => isFiniteCoord(s.lat, s.lon)).map((s) => [s.lon, s.lat])]),
    message: line ? null : GEOMETRY_MESSAGES[shapeItem ? 'no_shape' : 'failed'],
  };
}

/** Nearby results as map features, with the (browser-only) origin point and optional accuracy ring. */
export function nearbyMapData({ items, origin, accuracyM }) {
  const stops = stopsFeatures((items ?? []).map((s) => ({ id: s.stop_id, name: s.stop_name, lat: s.stop_lat, lon: s.stop_lon })));
  const coords = [...(items ?? []).map((s) => [s.stop_lon, s.stop_lat]), ...(origin ? [[origin.lon, origin.lat]] : [])];
  return { stops, origin: origin ? pointFeature(0, origin.lon, origin.lat, { role: 'user' }) : null, accuracy: origin && accuracyM > 0 ? circlePolygon(origin.lat, origin.lon, accuracyM) : null, bounds: boundsOf(coords) };
}

/** Polygon approximating a circle of `radiusM` metres (for an accuracy ring). Local equirectangular, fine at city scale. */
export function circlePolygon(lat, lon, radiusM, steps = 48) {
  const dLat = radiusM / 111_320;
  const dLon = radiusM / (111_320 * Math.cos((lat * Math.PI) / 180));
  const ring = Array.from({ length: steps + 1 }, (_, i) => {
    const a = (2 * Math.PI * (i % steps)) / steps;
    return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)];
  });
  return { type: 'Feature', properties: { role: 'accuracy' }, geometry: { type: 'Polygon', coordinates: [ring] } };
}

/** "850 m" / "1.2 km". */
export function formatDistance(m) {
  if (!Number.isFinite(m)) return '';
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10_000 ? 1 : 0)} km`;
}

const COMPASS_WORD = { N: 'north', NE: 'north-east', E: 'east', SE: 'south-east', S: 'south', SW: 'south-west', W: 'west', NW: 'north-west' };
export const compassWord = (c) => COMPASS_WORD[c] ?? '';

// --- distance / bearing between two real points (used to describe a cluster member relative to its place centre) ---
const R = 6_371_008.8;
const rad = (d) => (d * Math.PI) / 180;
export function distanceM(lat1, lon1, lat2, lon2) {
  const dp = rad(lat2 - lat1); const dl = rad(lon2 - lon1);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
export function bearingDeg(lat1, lon1, lat2, lon2) {
  const y = Math.sin(rad(lon2 - lon1)) * Math.cos(rad(lat2));
  const x = Math.cos(rad(lat1)) * Math.sin(rad(lat2)) - Math.sin(rad(lat1)) * Math.cos(rad(lat2)) * Math.cos(rad(lon2 - lon1));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
export const compassOf = (deg) => COMPASS[Math.floor(((deg % 360) + 22.5) / 45) % 8];

/** "40 m north of the place centre" for a cluster member, from real coordinates only; '' when it IS the centre. */
export function relativeToCentre(group, member) {
  if (!group || !Number.isFinite(group.centroid_lat) || !Number.isFinite(member.stop_lat)) return '';
  const d = distanceM(group.centroid_lat, group.centroid_lon, member.stop_lat, member.stop_lon);
  if (d < 5) return '';
  return `${formatDistance(d)} ${compassWord(compassOf(bearingDeg(group.centroid_lat, group.centroid_lon, member.stop_lat, member.stop_lon)))} of the place centre`;
}
