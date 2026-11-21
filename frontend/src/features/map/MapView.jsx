import './map.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { MAP_STYLE_URL } from '../../config.js';
import MapFallback from './MapFallback.jsx';
import { hasWebGL, prefersReducedMotion } from './webgl.js';

const SLOW_MS = 6000;
const defaultLoadEngine = () => import('./mapAdapter.js');
const boundsKey = (b) => (b ? b.flat().join(',') : '');

/**
 * Declarative map. Props are DATA, never imperative calls:
 *   data = { stops, line, origin, accuracy, bounds }  (GeoJSON from lib/geo.js)
 *   fallbackStops = [{ id, name, href? }]             (listed when the map cannot run)
 * The engine is created once per mount (data changes only update sources), listeners die with the adapter.
 * `loadEngine`, `checkWebGL` and `styleUrl` are injectable so every degradation path is testable without a GPU.
 */
export default function MapView({
  label, data, fallbackStops = [], selectedStopId = null, onSelectStop, onHoverStop, onPickPoint, className = '',
  loadEngine = defaultLoadEngine, checkWebGL = hasWebGL, styleUrl = MAP_STYLE_URL,
}) {
  const containerRef = useRef(null);
  const adapterRef = useRef(null);
  const dataRef = useRef(data);
  const lastBoundsRef = useRef(null);
  const cb = useRef({ onSelectStop, onHoverStop, onPickPoint });
  cb.current = { onSelectStop, onHoverStop, onPickPoint };
  dataRef.current = data;

  const [webglOk] = useState(() => checkWebGL());
  const [phase, setPhase] = useState(webglOk ? 'loading' : 'unavailable'); // loading | ready | unavailable
  const [reason, setReason] = useState(webglOk ? null : 'webgl');
  const [tilesFailed, setTilesFailed] = useState(false);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!webglOk) return undefined;
    let cancelled = false;
    let adapter = null;
    const slowTimer = setTimeout(() => { if (!cancelled) setSlow(true); }, SLOW_MS);
    loadEngine()
      .then((engine) => {
        if (cancelled || !containerRef.current) return;
        adapter = engine.createMapAdapter({
          container: containerRef.current, styleUrl, reducedMotion: prefersReducedMotion(),
          onStopClick: (id) => cb.current.onSelectStop?.(id),
          onStopHover: (id) => cb.current.onHoverStop?.(id),
          onPickPoint: cb.current.onPickPoint ? (p) => cb.current.onPickPoint?.(p) : undefined,
          onReady: () => { if (!cancelled) { setPhase('ready'); setSlow(false); } },
          onBasemapError: () => { if (!cancelled) setTilesFailed(true); },
          onFatalError: () => { if (!cancelled) { setReason('init'); setPhase('unavailable'); } },
        });
        adapterRef.current = adapter;
        adapter.setData(dataRef.current ?? {});
        lastBoundsRef.current = dataRef.current?.bounds ?? null;
        adapter.fitBounds(lastBoundsRef.current);
      })
      .catch(() => { if (!cancelled) { setReason('engine'); setPhase('unavailable'); } });
    return () => {
      cancelled = true;
      clearTimeout(slowTimer);
      adapterRef.current = null;
      adapter?.destroy();
    };
    // The engine is created once. Data, selection and callbacks flow through the effects/refs below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const key = boundsKey(data?.bounds);
  useEffect(() => {
    const a = adapterRef.current;
    if (!a) return;
    a.setData(data ?? {});
    if (key !== boundsKey(lastBoundsRef.current)) { lastBoundsRef.current = data?.bounds ?? null; a.fitBounds(lastBoundsRef.current); }
  }, [data, key]);

  useEffect(() => { adapterRef.current?.setSelected(selectedStopId); }, [selectedStopId]);

  const zoom = useCallback((d) => adapterRef.current?.zoomBy(d), []);
  const reset = useCallback(() => adapterRef.current?.fitBounds(lastBoundsRef.current), []);

  if (phase === 'unavailable') {
    return <section className={`map ${className}`} aria-label={label}><MapFallback reason={reason} stops={fallbackStops} /></section>;
  }
  return (
    <section className={`map ${className}`} aria-label={label}>
      <div className="map__frame">
        <div ref={containerRef} className="map__canvas" data-testid="map-canvas" />
        <div className="map__controls" role="group" aria-label="Map controls">
          <button type="button" className="map__btn" onClick={() => zoom(1)} disabled={phase !== 'ready'} aria-label="Zoom in">+</button>
          <button type="button" className="map__btn" onClick={() => zoom(-1)} disabled={phase !== 'ready'} aria-label="Zoom out">−</button>
          <button type="button" className="map__btn map__btn--text" onClick={reset} disabled={phase !== 'ready'}>Reset view</button>
        </div>
        {phase === 'loading' && <div className="map__loading" role="status">{slow ? 'The map is taking longer than usual to load. The list below has the same information.' : 'Loading map…'}</div>}
      </div>
      <div className="map__notices">
        {!styleUrl && <p className="map__notice" role="note">No street basemap is configured, so only the real route and stops are drawn.</p>}
        {tilesFailed && <p className="map__notice map__notice--warn" role="status">Street tiles could not be loaded. Showing the route and stops without a basemap.</p>}
      </div>
    </section>
  );
}
