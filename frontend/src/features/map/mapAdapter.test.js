import { beforeEach, describe, expect, it, vi } from 'vitest';

// A recording fake of the parts of MapLibre the adapter uses. Real WebGL rendering is NOT exercised here (UNVERIFIED).
const state = vi.hoisted(() => ({ maps: [] }));
vi.mock('maplibre-gl', () => {
  class FakeMap {
    constructor(opts) {
      this.opts = opts; this.handlers = {}; this.sources = {}; this.layers = {}; this.filters = {}; this.calls = []; this.removed = false; this.styleLoaded = true;
      this.canvas = { style: {}, setAttribute: (k, v) => { this.canvasAttrs = { ...this.canvasAttrs, [k]: v }; } };
      this.touchZoomRotate = { disableRotation: () => this.calls.push('disableRotation') };
      state.maps.push(this);
    }
    on(evt, a, b) { const [layer, fn] = typeof a === 'string' ? [a, b] : [null, a]; (this.handlers[evt + (layer ? `@${layer}` : '')] ??= []).push(fn); }
    emit(evt, payload, layer) { (this.handlers[evt + (layer ? `@${layer}` : '')] ?? []).forEach((f) => f(payload)); }
    addControl(c, pos) { this.calls.push(['addControl', c.kind, pos, c.opts]); }
    addSource(id, def) { this.sources[id] = { def, data: def.data, setData: (d) => { this.sources[id].data = d; } }; }
    getSource(id) { return this.sources[id]; }
    addLayer(def) { this.layers[def.id] = def; }
    getLayer(id) { return this.layers[id]; }
    setFilter(id, f) { this.filters[id] = f; }
    isStyleLoaded() { return this.styleLoaded; }
    setStyle(style) { this.calls.push(['setStyle', style.name ?? style]); this.sources = {}; this.layers = {}; this.emit('style.load'); }
    queryRenderedFeatures() { return this.hit ?? []; }
    getCanvas() { return this.canvas; }
    getZoom() { return 10; }
    zoomTo(z, o) { this.calls.push(['zoomTo', z, o]); }
    fitBounds(b, o) { this.calls.push(['fitBounds', b, o]); }
    jumpTo(o) { this.calls.push(['jumpTo', o]); }
    resize() { this.calls.push('resize'); }
    remove() { this.removed = true; }
  }
  class AttributionControl { constructor(opts) { this.kind = 'attribution'; this.opts = opts; } }
  return { Map: FakeMap, AttributionControl };   // maplibre-gl 6 exposes NAMED exports only (no default): mirror the real module shape
});

const { createMapAdapter, BLANK_STYLE } = await import('./mapAdapter.js');
const container = () => document.createElement('div');
const fc = (n) => ({ type: 'FeatureCollection', features: Array.from({ length: n }, (_, i) => ({ type: 'Feature', properties: { stopId: String(i) }, geometry: { type: 'Point', coordinates: [77, 28] } })) });

beforeEach(() => { state.maps.length = 0; });

describe('createMapAdapter', () => {
  it('uses the configured style URL; with none it uses the tile-less BLANK_STYLE (zero third-party requests)', () => {
    createMapAdapter({ container: container(), styleUrl: 'https://tiles.example/s.json' });
    createMapAdapter({ container: container(), styleUrl: '' });
    expect(state.maps[0].opts.style).toBe('https://tiles.example/s.json');
    expect(state.maps[1].opts.style).toBe(BLANK_STYLE);
    expect(Object.keys(BLANK_STYLE.sources)).toEqual([]);
  });

  it('always shows attribution (provider text comes from the style; ours is added) and keeps mobile scrolling usable', () => {
    createMapAdapter({ container: container(), styleUrl: '' });
    const m = state.maps[0];
    expect(m.calls.find((c) => c[0] === 'addControl')).toEqual(['addControl', 'attribution', 'bottom-right', expect.objectContaining({ compact: true, customAttribution: expect.stringContaining('Delhi GTFS') })]);
    expect(m.opts.attributionControl).toBe(false);          // we add ours explicitly, never silently dropped
    expect(m.opts.cooperativeGestures).toBe(true);          // no scroll trap
    expect(m.opts.dragRotate).toBe(false);
  });

  it('adds one GeoJSON source per data kind and the layer stack on style.load', () => {
    createMapAdapter({ container: container() });
    const m = state.maps[0]; m.emit('style.load');
    expect(Object.keys(m.sources).sort()).toEqual(['accuracy', 'line', 'origin', 'stops']);
    expect(Object.keys(m.layers)).toEqual(['accuracy-fill', 'accuracy-line', 'line-casing', 'line', 'stops-circle', 'stops-selected', 'origin-dot']);
    expect(Object.values(m.layers).every((l) => l.type !== 'symbol')).toBe(true);   // no text layers: a tile-less style has no glyphs
  });

  it('large point sets are GeoJSON sources, not DOM markers', () => {
    const a = createMapAdapter({ container: container() });
    const m = state.maps[0]; m.emit('style.load');
    a.setData({ stops: fc(5000) });
    expect(m.sources.stops.data.features).toHaveLength(5000);
    expect(container().children).toHaveLength(0);
  });

  it('setData pushes exactly what it was given; a null line clears the line source (nothing is invented)', () => {
    const a = createMapAdapter({ container: container() });
    const m = state.maps[0]; m.emit('style.load');
    const line = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[77, 28], [77.1, 28.1]] } };
    a.setData({ stops: fc(2), line });
    expect(m.sources.line.data).toBe(line);
    a.setData({ stops: fc(2), line: null });
    expect(m.sources.line.data).toEqual({ type: 'FeatureCollection', features: [] });
  });

  it('data set BEFORE the style finished loading is applied once it does', () => {
    const a = createMapAdapter({ container: container() });
    const m = state.maps[0]; m.styleLoaded = false;
    a.setData({ stops: fc(3) });
    m.styleLoaded = true; m.emit('style.load');
    expect(m.sources.stops.data.features).toHaveLength(3);
  });

  it('basemap failure -> falls back to BLANK_STYLE, re-adds layers/data, reports once; own-source errors are ignored', () => {
    const onBasemapError = vi.fn();
    const a = createMapAdapter({ container: container(), styleUrl: 'https://tiles.example/s.json', onBasemapError });
    const m = state.maps[0]; m.emit('style.load'); a.setData({ stops: fc(2) });
    m.emit('error', { sourceId: 'stops', error: new Error('own') });
    expect(onBasemapError).not.toHaveBeenCalled();
    m.emit('error', { sourceId: 'osm', error: new Error('tile 500') });
    m.emit('error', { sourceId: 'osm', error: new Error('tile 500 again') });
    expect(onBasemapError).toHaveBeenCalledTimes(1);
    expect(m.calls).toContainEqual(['setStyle', 'crowdsense-blank']);
    expect(m.sources.stops.data.features).toHaveLength(2);   // data survived the style swap
  });

  it('without a basemap there is nothing to fall back from', () => {
    const onBasemapError = vi.fn();
    createMapAdapter({ container: container(), styleUrl: '', onBasemapError });
    state.maps[0].emit('error', { sourceId: 'x', error: new Error('?') });
    expect(onBasemapError).not.toHaveBeenCalled();
  });

  it('click/hover on stops are reported by stop id', () => {
    const onStopClick = vi.fn(); const onStopHover = vi.fn();
    createMapAdapter({ container: container(), onStopClick, onStopHover });
    const m = state.maps[0];
    m.emit('click', { features: [{ properties: { stopId: 'S7' } }] }, 'stops-circle');
    m.emit('mousemove', { features: [{ properties: { stopId: 'S8' } }] }, 'stops-circle');
    m.emit('mouseleave', {}, 'stops-circle');
    expect(onStopClick).toHaveBeenCalledWith('S7');
    expect(onStopHover.mock.calls.map((c) => c[0])).toEqual(['S8', null]);
  });

  it('click on empty map is a POINT (never a stop); click on a stop is not a pick', () => {
    const onPickPoint = vi.fn(); const onStopClick = vi.fn();
    createMapAdapter({ container: container(), onPickPoint, onStopClick });
    const m = state.maps[0]; m.emit('style.load');
    m.hit = [];
    m.emit('click', { lngLat: { lat: 28.61, lng: 77.21 }, point: { x: 1, y: 1 } });
    expect(onPickPoint).toHaveBeenCalledWith({ lat: 28.61, lon: 77.21 });
    m.hit = [{ properties: { stopId: 'S1' } }];
    m.emit('click', { lngLat: { lat: 28.7, lng: 77.3 }, point: { x: 2, y: 2 } });
    expect(onPickPoint).toHaveBeenCalledTimes(1);
  });

  it('reduced motion: no animated camera moves', () => {
    const a = createMapAdapter({ container: container(), reducedMotion: true });
    const m = state.maps[0];
    a.fitBounds([[77, 28], [77.1, 28.1]]); a.zoomBy(1);
    expect(m.calls.find((c) => c[0] === 'fitBounds')[2]).toMatchObject({ animate: false, duration: 0 });
    expect(m.calls.find((c) => c[0] === 'zoomTo')[2]).toMatchObject({ animate: false, duration: 0 });
    expect(m.opts.fadeDuration).toBe(0);
  });

  it('a single-point bounds is a jump (no degenerate fitBounds); null bounds is a no-op', () => {
    const a = createMapAdapter({ container: container() });
    const m = state.maps[0];
    a.fitBounds([[77, 28], [77, 28]]); a.fitBounds(null);
    expect(m.calls.filter((c) => c[0] === 'jumpTo')).toHaveLength(1);
    expect(m.calls.filter((c) => c[0] === 'fitBounds')).toHaveLength(0);
  });

  it('selected stop is a filter on the highlight layer; destroy removes the map', () => {
    const a = createMapAdapter({ container: container() });
    const m = state.maps[0]; m.emit('style.load');
    a.setSelected('S9');
    expect(m.filters['stops-selected']).toEqual(['==', ['get', 'stopId'], 'S9']);
    a.destroy();
    expect(m.removed).toBe(true);
  });

  it('gives the canvas an accessible description pointing to the text list', () => {
    createMapAdapter({ container: container() });
    expect(state.maps[0].canvasAttrs['aria-label']).toMatch(/same information is listed as text/);
  });
});
