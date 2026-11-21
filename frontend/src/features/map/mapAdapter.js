// The ONLY file that imports the map engine (MapLibre GL JS). It is loaded with a dynamic import() from MapView, so
// the engine and its CSS are a separate chunk that is downloaded only on pages that show a map. Everything the rest of
// the app knows about it is the small contract returned by createMapAdapter(), so tests can replace it at this boundary.
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { NCR_CENTER } from '../../lib/geo.js';

/** A style with no tiles: draws only our own GeoJSON layers. Used when no style is configured or the tiles fail. */
export const BLANK_STYLE = { version: 8, name: 'crowdsense-blank', sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e9edf1' } }] };

export const COLORS = { board: '#146c2e', alight: '#b3261e', current: '#b45309', sibling: '#0e7490', stop: '#1f4e8c', line: '#1f4e8c', casing: '#ffffff', user: '#6d28d9', halo: '#ffffff', accuracy: '#6d28d9' };
const OWN_SOURCES = new Set(['stops', 'line', 'origin', 'accuracy']);
const empty = { type: 'FeatureCollection', features: [] };

/**
 * @param {object} o
 * @param {HTMLElement} o.container
 * @param {string} [o.styleUrl]  empty -> BLANK_STYLE
 * @param {boolean} [o.reducedMotion]
 * @param {(stopId:string)=>void} [o.onStopClick]
 * @param {(stopId:string|null)=>void} [o.onStopHover]
 * @param {(p:{lat:number,lon:number})=>void} [o.onPickPoint]  click on empty map (not on a stop). A point is NEVER treated as a stop.
 * @param {()=>void} [o.onReady]           first successful render of the style
 * @param {(reason:string)=>void} [o.onBasemapError]  tiles/style failed; the adapter has already fallen back to BLANK_STYLE
 * @param {(err:Error)=>void} [o.onFatalError]
 */
export function createMapAdapter({ container, styleUrl = '', reducedMotion = false, onStopClick, onStopHover, onPickPoint, onReady, onBasemapError, onFatalError }) {
  let data = { stops: empty, line: null, origin: null, accuracy: null };
  let selected = '';
  let usingBasemap = Boolean(styleUrl);
  let basemapFailed = false;
  let destroyed = false;
  let readyFired = false;

  const map = new maplibregl.Map({
    container, style: usingBasemap ? styleUrl : BLANK_STYLE, center: NCR_CENTER, zoom: 9, minZoom: 6, maxZoom: 19,
    attributionControl: false, dragRotate: false, pitchWithRotate: false, touchPitch: false,
    cooperativeGestures: true, // one-finger scroll moves the PAGE, two fingers move the map: no scroll trap on phones
    fadeDuration: reducedMotion ? 0 : 300,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'Route and stop data: Delhi GTFS (static timetable)' }), 'bottom-right');

  const addLayers = () => {
    if (destroyed) return;
    const add = (id, src) => { if (!map.getSource(id)) map.addSource(id, { type: 'geojson', data: src }); };
    add('accuracy', empty); add('line', empty); add('stops', empty); add('origin', empty);
    const layer = (def) => { if (!map.getLayer(def.id)) map.addLayer(def); };
    layer({ id: 'accuracy-fill', type: 'fill', source: 'accuracy', paint: { 'fill-color': COLORS.accuracy, 'fill-opacity': 0.12 } });
    layer({ id: 'accuracy-line', type: 'line', source: 'accuracy', paint: { 'line-color': COLORS.accuracy, 'line-width': 1.5, 'line-dasharray': [2, 2] } });
    layer({ id: 'line-casing', type: 'line', source: 'line', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': COLORS.casing, 'line-width': 9 } });
    layer({ id: 'line', type: 'line', source: 'line', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': COLORS.line, 'line-width': 5 } });
    layer({
      id: 'stops-circle', type: 'circle', source: 'stops',
      paint: {
        'circle-radius': ['match', ['get', 'role'], 'board', 9, 'alight', 9, 'current', 9, 6],
        'circle-color': ['match', ['get', 'role'], 'board', COLORS.board, 'alight', COLORS.alight, 'current', COLORS.current, 'sibling', COLORS.sibling, COLORS.stop],
        'circle-stroke-color': COLORS.halo, 'circle-stroke-width': 2.5,
      },
    });
    layer({ id: 'stops-selected', type: 'circle', source: 'stops', filter: ['==', ['get', 'stopId'], selected], paint: { 'circle-radius': 13, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#111827', 'circle-stroke-width': 3 } });
    layer({ id: 'origin-dot', type: 'circle', source: 'origin', paint: { 'circle-radius': 8, 'circle-color': COLORS.user, 'circle-stroke-color': COLORS.halo, 'circle-stroke-width': 3 } });
    pushData();
  };

  function pushData() {
    if (destroyed || !map.isStyleLoaded?.() && !map.getSource('stops')) return;
    map.getSource('stops')?.setData(data.stops ?? empty);
    map.getSource('line')?.setData(data.line ?? empty);
    map.getSource('origin')?.setData(data.origin ?? empty);
    map.getSource('accuracy')?.setData(data.accuracy ?? empty);
    if (map.getLayer('stops-selected')) map.setFilter('stops-selected', ['==', ['get', 'stopId'], selected]);
  }

  map.on('style.load', addLayers);
  map.on('load', () => { if (!readyFired && !destroyed) { readyFired = true; onReady?.(); } });
  map.on('error', (e) => {
    if (destroyed) return;
    const own = e?.sourceId && OWN_SOURCES.has(e.sourceId);
    if (own || !usingBasemap || basemapFailed) return;   // only a failing basemap (style JSON, tiles, glyphs, sprites) triggers the fallback
    basemapFailed = true; usingBasemap = false;
    map.setStyle(BLANK_STYLE);                           // style.load re-adds our layers and data
    onBasemapError?.(String(e?.error?.message ?? 'basemap request failed'));
  });
  map.on('click', 'stops-circle', (e) => { const id = e.features?.[0]?.properties?.stopId; if (id) onStopClick?.(id); });
  map.on('click', (e) => {
    if (!onPickPoint || !e?.lngLat) return;
    const hit = map.getLayer('stops-circle') ? map.queryRenderedFeatures(e.point, { layers: ['stops-circle'] }) : [];
    if (!hit.length) onPickPoint({ lat: e.lngLat.lat, lon: e.lngLat.lng });
  });
  map.on('mouseenter', 'stops-circle', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mousemove', 'stops-circle', (e) => onStopHover?.(e.features?.[0]?.properties?.stopId ?? null));
  map.on('mouseleave', 'stops-circle', () => { map.getCanvas().style.cursor = ''; onStopHover?.(null); });
  map.getCanvas().setAttribute('aria-label', 'Map canvas. Arrow keys pan, plus and minus zoom. The same information is listed as text on this page.');

  try { map.resize(); } catch (err) { onFatalError?.(err); }

  return {
    /** data = { stops, line, origin, accuracy }: GeoJSON exactly as built by lib/geo.js */
    setData(next) { data = { stops: next.stops ?? empty, line: next.line ?? null, origin: next.origin ?? null, accuracy: next.accuracy ?? null }; pushData(); },
    setSelected(id) { selected = id ?? ''; if (map.getLayer('stops-selected')) map.setFilter('stops-selected', ['==', ['get', 'stopId'], selected]); },
    fitBounds(bounds, { padding = 48, maxZoom = 16 } = {}) {
      if (!bounds) return;
      const same = bounds[0][0] === bounds[1][0] && bounds[0][1] === bounds[1][1];
      if (same) map.jumpTo({ center: bounds[0], zoom: 15 });
      else map.fitBounds(bounds, { padding, maxZoom, animate: !reducedMotion, duration: reducedMotion ? 0 : 400 });
    },
    zoomBy(delta) { map.zoomTo(map.getZoom() + delta, { animate: !reducedMotion, duration: reducedMotion ? 0 : 200 }); },
    resize() { if (!destroyed) map.resize(); },
    destroy() { destroyed = true; map.remove(); },
  };
}
