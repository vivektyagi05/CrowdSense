import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { getNearbyStops } from '../api/endpoints.js';
import BottomSheet from '../features/map/BottomSheet.jsx';
import LazyMapView from '../features/map/LazyMapView.jsx';
import { GEO_MESSAGES, useGeolocation } from '../hooks/useGeolocation.js';
import { useAsync } from '../hooks/useAsync.js';
import { compassWord, formatDistance, inServiceArea, nearbyMapData } from '../lib/geo.js';
import { writeSearch } from '../lib/searchParams.js';
import { usePageTitle } from '../lib/title.js';
import Button from '../ui/Button.jsx';
import { EmptyState, ErrorState, Notice, Skeleton } from '../ui/States.jsx';

const RADII = [100, 250, 500, 1000, 2000, 3000];
const DEFAULT_RADIUS = 500;
const href = (id) => `/stops/${encodeURIComponent(id)}`;

/**
 * Stops near a point. The point is either the visitor's position (explicit button click) or a tapped map point. It is
 * kept in component state only: never in the URL, storage or logs. The URL holds only the chosen origin/destination
 * STOP ids, so a half-built journey can be shared.
 */
export default function NearbyPage() {
  usePageTitle('Stops near you');
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const fromId = params.get('from') ?? '';
  const toId = params.get('to') ?? '';
  const geo = useGeolocation();
  const [picked, setPicked] = useState(null);          // { lat, lon } from a map tap
  const [radius, setRadius] = useState(DEFAULT_RADIUS);
  const [selected, setSelected] = useState(null);
  const [areaError, setAreaError] = useState(null);

  const origin = picked ?? (geo.position ? { lat: geo.position.lat, lon: geo.position.lon } : null);
  const accuracy = picked ? null : geo.position?.accuracy ?? null;

  const near = useAsync(origin ? `nearby:${origin.lat.toFixed(6)}:${origin.lon.toFixed(6)}:${radius}` : null,
    (signal) => getNearbyStops({ lat: origin.lat, lon: origin.lon, radiusM: radius, limit: 30 }, { signal }));
  const items = near.data?.items ?? [];

  const data = useMemo(() => nearbyMapData({ items, origin, accuracyM: accuracy }), [items, origin, accuracy]);
  const fallback = useMemo(() => items.map((s) => ({ id: s.stop_id, name: s.stop_name, href: href(s.stop_id) })), [items]);

  function pickPoint(p) {
    if (!inServiceArea(p.lat, p.lon)) { setAreaError('That point is outside the Delhi-NCR area CrowdSense covers. Pick a point inside Delhi-NCR.'); return; }
    setAreaError(null); setPicked(p); setSelected(null);
  }
  function useMine() { setPicked(null); setAreaError(null); geo.request(); }

  const setStop = (key, id) => { const next = new URLSearchParams(params); if (id) next.set(key, id); else next.delete(key); setParams(next, { replace: true }); };
  const chosen = items.find((s) => s.stop_id === selected);
  const canSearch = fromId && toId && fromId !== toId;

  return (
    <div className="container page">
      <div className="page-head">
        <h1>Stops near you</h1>
        <p className="muted">Find real bus stops around where you are, or around any point you tap on the map, and use one as your origin or destination.</p>
      </div>
      <div className="map-layout">
        <div className="map-layout__map">
          <LazyMapView label="Map of nearby stops" data={data} fallbackStops={fallback} selectedStopId={selected} onSelectStop={setSelected} onPickPoint={pickPoint} />
          <p className="muted map-legend"><span className="legend legend--user" /> Your point · <span className="legend legend--stop" /> Stops. Tap an empty spot on the map to search there.</p>
          {chosen && <p className="stop-callout"><span className="stop-callout__name">{chosen.stop_name}</span><Link to={href(chosen.stop_id)}>Open stop page</Link></p>}
        </div>
        <BottomSheet title={origin ? `${items.length} stops nearby` : 'Find stops near you'} className="nearby-sheet">
          <div className="nearby-controls">
            <Button onClick={useMine} loading={geo.state === 'requesting'}>Use my location</Button>
            <label className="field-inline">
              <span>Search radius</span>
              <select value={radius} onChange={(e) => setRadius(Number(e.target.value))} aria-label="Search radius">
                {RADII.map((r) => <option key={r} value={r}>{formatDistance(r)}</option>)}
              </select>
            </label>
          </div>
          <p className="muted privacy-note">Your location stays in this browser. When you search, the coordinates are sent only to the CrowdSense server to find stops; they are not stored or logged. Your exact position is never sent to the map provider, but, like any web map, the provider can see which map tiles (the general area) are loaded.</p>
          {geo.state === 'requesting' && <p role="status" className="muted">Waiting for your device… allow the location prompt if it appears.</p>}
          {GEO_MESSAGES[geo.state] && !picked && <Notice tone="warning">{GEO_MESSAGES[geo.state]}</Notice>}
          {areaError && <Notice tone="warning">{areaError}</Notice>}
          {geo.lowAccuracy && !picked && <Notice tone="warning">Your location is only accurate to about {formatDistance(geo.position.accuracy)} (the purple ring on the map). Stops listed may not be the closest to you; check the map.</Notice>}
          {!origin && geo.state !== 'requesting' && <EmptyState title="No point chosen yet">Press “Use my location”, or tap a spot on the map. Nothing is requested until you do.</EmptyState>}
          {origin && near.status === 'loading' && <Skeleton lines={4} label="Finding stops" />}
          {near.status === 'failed' && <ErrorState title="Could not find nearby stops" error={near.error} onRetry={near.retry} />}
          {near.status === 'ready' && items.length === 0 && <EmptyState title={`No stops within ${formatDistance(radius)}`}>Try a larger radius or another point.</EmptyState>}
          {items.length > 0 && (
            <>
              <p className="muted">Nearest first, by straight-line distance (not walking distance). Showing {items.length}{near.data.total_in_radius > items.length ? ` of ${near.data.total_in_radius}` : ''} within {formatDistance(radius)}.</p>
              <ol className="place-list nearby-list" aria-label="Nearby stops">
                {items.map((s) => (
                  <li key={s.stop_id} className={`place-list__item${s.stop_id === selected ? ' place-list__item--active' : ''}`} onMouseEnter={() => setSelected(s.stop_id)} onMouseLeave={() => setSelected(null)}>
                    <Link to={href(s.stop_id)} onFocus={() => setSelected(s.stop_id)} onBlur={() => setSelected(null)}>{s.stop_name}</Link>
                    <span className="muted tnum">{formatDistance(s.distance_m)} {compassWord(s.compass)}{s.route_names.length ? ` · routes ${s.route_names.slice(0, 4).join(', ')}${s.routes_count > 4 ? ` +${s.routes_count - 4}` : ''}` : ''}</span>
                    <span className="nearby-list__actions">
                      <Button size="sm" variant={fromId === s.stop_id ? 'primary' : 'secondary'} aria-pressed={fromId === s.stop_id} onClick={() => setStop('from', fromId === s.stop_id ? '' : s.stop_id)}>Use as origin</Button>
                      <Button size="sm" variant={toId === s.stop_id ? 'primary' : 'secondary'} aria-pressed={toId === s.stop_id} onClick={() => setStop('to', toId === s.stop_id ? '' : s.stop_id)}>Use as destination</Button>
                    </span>
                  </li>
                ))}
              </ol>
            </>
          )}
          {(fromId || toId) && (
            <div className="panel nearby-journey" aria-label="Your journey so far">
              <p><strong>Journey so far:</strong> origin {fromId ? <Link to={href(fromId)}>stop {fromId}</Link> : 'not chosen'} · destination {toId ? <Link to={href(toId)}>stop {toId}</Link> : 'not chosen'}</p>
              {fromId && toId && fromId === toId && <Notice tone="warning">Origin and destination must be different stops.</Notice>}
              <Button disabled={!canSearch} onClick={() => navigate(`/journeys?${writeSearch({ fromId, toId })}`)}>Continue to journey search</Button>
              {!canSearch && fromId && !toId && <Link to={`/journeys?${writeSearch({ fromId })}`}>Choose the destination in the search form</Link>}
            </div>
          )}
        </BottomSheet>
      </div>
    </div>
  );
}
