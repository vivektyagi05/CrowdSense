import { describe, expect, it } from 'vitest';
import * as geo from './geo.js';

const ok = { status: 'ok', coordinates: [[77.2, 28.6], [77.21, 28.61], [77.22, 28.6]] };
const stops = [
  { id: 'A', name: 'Alpha', lat: 28.6, lon: 77.2, sequence: 1 }, { id: 'B', name: 'Beta', lat: 28.61, lon: 77.21, sequence: 2 },
  { id: 'C', name: 'Gamma', lat: 28.6, lon: 77.22, sequence: 3 }, { id: 'X', name: 'No coords', lat: null, lon: null, sequence: 4 },
];

describe('legacy helpers (unchanged)', () => {
  it('toMapStops skips rows without coordinates', () => {
    expect(geo.toMapStops([{ stop_id: 'A', stop_name: 'a', stop_lat: 1, stop_lon: 2, stop_sequence: 1 }, { stop_id: 'B', stop_lat: null }])).toHaveLength(1);
  });
});

describe('boundsOf', () => {
  it('bounds [lon, lat] pairs and ignores junk', () => {
    expect(geo.boundsOf([[77.2, 28.6], [77.3, 28.7], [NaN, 1], null, 'x', [200, 0]])).toEqual([[77.2, 28.6], [77.3, 28.7]]);
  });
  it('is null when nothing is finite', () => {
    expect(geo.boundsOf([])).toBeNull();
    expect(geo.boundsOf(undefined)).toBeNull();
    expect(geo.boundsOf([[NaN, NaN]])).toBeNull();
  });
});

describe('lineFeature - never a guess', () => {
  it('returns the API coordinates exactly', () => {
    expect(geo.lineFeature(ok.coordinates).geometry.coordinates).toEqual(ok.coordinates);
  });
  it('needs at least two real points', () => {
    expect(geo.lineFeature([])).toBeNull();
    expect(geo.lineFeature([[77.2, 28.6]])).toBeNull();
    expect(geo.lineFeature(undefined)).toBeNull();
    expect(geo.lineFeature([[77.2, 28.6], [NaN, 1]])).toBeNull();
  });
  it('the module exposes no function that builds a line from stops', () => {
    const names = Object.keys(geo);
    expect(names.filter((n) => /line|path|polyline|route/i.test(n)).sort()).toEqual(['lineFeature', 'routeMapData']);
    expect(geo.lineFeature.length).toBeLessThanOrEqual(2); // (coordinates, properties) - no stops parameter
  });
});

describe('legMapData', () => {
  it('ok: line is exactly the API geometry; stops carry board/alight roles', () => {
    const d = geo.legMapData({ shape: ok, stops, boardId: 'A', alightId: 'C' });
    expect(d.status).toBe('ok');
    expect(d.line.geometry.coordinates).toEqual(ok.coordinates);
    expect(d.message).toBeNull();
    expect(d.stops.features.map((f) => f.properties.role)).toEqual(['board', 'stop', 'alight']);
    expect(d.stops.features).toHaveLength(3); // the row without coordinates is skipped
    expect(d.bounds).toEqual([[77.2, 28.6], [77.22, 28.61]]);
  });
  it.each([
    ['no_shape', /not published/],
    ['unreliable_projection', /could not be matched reliably/],
    ['failed', /could not be loaded/],
  ])('%s: NO line, honest message, stops still present', (status, msg) => {
    const d = geo.legMapData({ shape: status === 'failed' ? null : { status, coordinates: [] }, stops, boardId: 'A', alightId: 'C' });
    expect(d.line).toBeNull();
    expect(d.status).toBe(status);
    expect(d.message).toMatch(msg);
    expect(d.stops.features).toHaveLength(3);
    expect(d.bounds).not.toBeNull(); // the map can still frame the stops
  });
  it('ok status with fewer than 2 coordinates is treated as no_shape, not drawn', () => {
    const d = geo.legMapData({ shape: { status: 'ok', coordinates: [[77.2, 28.6]] }, stops, boardId: 'A', alightId: 'C' });
    expect(d.line).toBeNull();
    expect(d.status).toBe('no_shape');
  });
  it('even a response that smuggles coordinates with a non-ok status draws nothing', () => {
    const d = geo.legMapData({ shape: { status: 'unreliable_projection', coordinates: ok.coordinates }, stops, boardId: 'A', alightId: 'C' });
    expect(d.line).toBeNull();
  });
});

describe('routeMapData', () => {
  it('draws only an ok shape item', () => {
    expect(geo.routeMapData({ shapeItem: { geometry_status: 'ok', coordinates: ok.coordinates }, stops }).line.geometry.coordinates).toEqual(ok.coordinates);
    const no = geo.routeMapData({ shapeItem: { geometry_status: 'no_shape', coordinates: [] }, stops });
    expect(no.line).toBeNull();
    expect(no.message).toMatch(/not published/);
    expect(geo.routeMapData({ shapeItem: undefined, stops }).status).toBe('failed');
  });
});

describe('nearbyMapData', () => {
  const items = [{ stop_id: 'A', stop_name: 'Alpha', stop_lat: 28.6, stop_lon: 77.2 }];
  it('keeps the origin separate from stops and adds an accuracy ring only with an accuracy', () => {
    const d = geo.nearbyMapData({ items, origin: { lat: 28.601, lon: 77.201 }, accuracyM: 80 });
    expect(d.stops.features).toHaveLength(1);
    expect(d.origin.geometry.coordinates).toEqual([77.201, 28.601]);
    expect(d.accuracy.geometry.type).toBe('Polygon');
    expect(geo.nearbyMapData({ items, origin: { lat: 28.6, lon: 77.2 } }).accuracy).toBeNull();
    expect(geo.nearbyMapData({ items, origin: null }).origin).toBeNull();
  });
});

describe('circlePolygon / distance / area', () => {
  it('ring is closed, ~radius away from the centre', () => {
    const ring = geo.circlePolygon(28.6, 77.2, 100).geometry.coordinates[0];
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    const dLat = Math.abs(ring[12][1] - 28.6) * 111_320; // quarter turn = due north
    expect(Math.round(dLat)).toBe(100);
  });
  it('formatDistance', () => {
    expect([geo.formatDistance(49.6), geo.formatDistance(850), geo.formatDistance(1234), geo.formatDistance(15_400), geo.formatDistance(NaN)]).toEqual(['50 m', '850 m', '1.2 km', '15 km', '']);
  });
  it('inServiceArea matches the backend box including edges', () => {
    expect(geo.inServiceArea(28.6, 77.2)).toBe(true);
    expect(geo.inServiceArea(28.0, 76.4)).toBe(true);
    expect(geo.inServiceArea(29.5, 77.8)).toBe(true);
    expect(geo.inServiceArea(19.07, 72.87)).toBe(false);
    expect(geo.inServiceArea(NaN, 77)).toBe(false);
  });
  it('compassWord', () => {
    expect([geo.compassWord('NE'), geo.compassWord('S'), geo.compassWord('?')]).toEqual(['north-east', 'south', '']);
  });
});
