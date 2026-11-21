import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCluster, getNearbyStops } from '../../api/endpoints.js';
import { useAsync } from '../../hooks/useAsync.js';
import { compassWord, formatDistance, stopsFeatures, boundsOf, GEOMETRY_MESSAGES } from '../../lib/geo.js';
import { EmptyState, ErrorState, Skeleton } from '../../ui/States.jsx';
import LazyMapView from './LazyMapView.jsx';

const RADIUS_M = 400;
const href = (id) => `/stops/${encodeURIComponent(id)}`;

/**
 * Stop page map: this stop (amber), the other physical stops of the same place cluster (teal) and nearby stops (blue).
 * The origin of the nearby search is the STOP's own published coordinates, never the visitor's position.
 * Every marker is also a row in the lists below (text equivalent).
 */
export default function StopAround({ stop }) {
  const [selected, setSelected] = useState(null);
  const cluster = useAsync(stop.cluster_id ? `cl:${stop.cluster_id}` : null, () => getCluster(stop.cluster_id));
  const near = useAsync(`near:${stop.stop_id}`, (signal) => getNearbyStops({ lat: stop.stop_lat, lon: stop.stop_lon, radiusM: RADIUS_M, limit: 20 }, { signal }));

  const siblings = useMemo(() => (cluster.data?.members ?? []).filter((m) => m.stop_id !== stop.stop_id), [cluster.data, stop.stop_id]);
  const nearby = useMemo(() => (near.data?.items ?? []).filter((m) => m.stop_id !== stop.stop_id && !siblings.some((s) => s.stop_id === m.stop_id)), [near.data, siblings]);

  const data = useMemo(() => {
    const roles = { [stop.stop_id]: 'current', ...Object.fromEntries(siblings.map((s) => [s.stop_id, 'sibling'])) };
    const all = [
      { id: stop.stop_id, name: stop.stop_name, lat: stop.stop_lat, lon: stop.stop_lon },
      ...siblings.map((s) => ({ id: s.stop_id, name: s.stop_name, lat: s.stop_lat, lon: s.stop_lon })),
      ...nearby.map((s) => ({ id: s.stop_id, name: s.stop_name, lat: s.stop_lat, lon: s.stop_lon })),
    ];
    return { stops: stopsFeatures(all, { roles }), line: null, bounds: boundsOf(all.map((s) => [s.lon, s.lat])) };
  }, [stop, siblings, nearby]);
  const fallback = useMemo(() => [{ id: stop.stop_id, name: stop.stop_name }, ...siblings.map((s) => ({ id: s.stop_id, name: s.stop_name, href: href(s.stop_id) })), ...nearby.map((s) => ({ id: s.stop_id, name: s.stop_name, href: href(s.stop_id) }))], [stop, siblings, nearby]);
  const picked = selected && selected !== stop.stop_id ? [...siblings, ...nearby].find((s) => s.stop_id === selected) : null;

  return (
    <section className="panel" aria-labelledby="around-title">
      <h2 id="around-title">Around this stop</h2>
      <div className="map-layout">
        <div className="map-layout__map">
          <LazyMapView label={`Map around ${stop.stop_name}`} data={data} fallbackStops={fallback} selectedStopId={selected} onSelectStop={setSelected} />
          <p className="muted map-legend"><span className="legend legend--current" /> This stop · <span className="legend legend--sibling" /> Same place · <span className="legend legend--stop" /> Within {RADIUS_M} m</p>
          {picked && <p className="stop-callout"><span className="stop-callout__name">{picked.stop_name}</span><Link to={href(picked.stop_id)}>Open stop page</Link></p>}
        </div>
        <div className="map-layout__details">
          {stop.cluster_id && (
            <>
              <h3>Same place, other stops</h3>
              {cluster.status === 'loading' && <Skeleton lines={2} label="Loading place" />}
              {cluster.status === 'failed' && <ErrorState title="Could not load the place" error={cluster.error} onRetry={cluster.retry} />}
              {cluster.status === 'ready' && siblings.length === 0 && <p className="muted">This is the only stop with this name nearby.</p>}
              {siblings.length > 0 && <p className="muted">These stops share this name and are close together (often opposite sides of a road). Make sure you board at the right one.</p>}
              <PlaceList items={siblings} selected={selected} onSelect={setSelected} kind="sibling" />
            </>
          )}
          <h3>Nearby stops</h3>
          {near.status === 'loading' && <Skeleton lines={3} label="Loading nearby stops" />}
          {near.status === 'failed' && <ErrorState title="Could not load nearby stops" error={near.error} onRetry={near.retry} />}
          {near.status === 'ready' && nearby.length === 0 && <EmptyState title="No other stops within 400 m">Nothing else is published within {RADIUS_M} m of this stop.</EmptyState>}
          <PlaceList items={nearby} selected={selected} onSelect={setSelected} kind="nearby" />
          {near.status === 'ready' && <p className="muted">Distances are straight-line from this stop, not walking distances.</p>}
        </div>
      </div>
    </section>
  );
}

function PlaceList({ items, selected, onSelect, kind }) {
  if (!items.length) return null;
  return (
    <ul className="place-list" aria-label={kind === 'sibling' ? 'Other stops at this place' : 'Nearby stops'}>
      {items.map((s) => (
        <li key={s.stop_id} className={s.stop_id === selected ? 'place-list__item place-list__item--active' : 'place-list__item'} onMouseEnter={() => onSelect(s.stop_id)} onMouseLeave={() => onSelect(null)}>
          <Link to={href(s.stop_id)} onFocus={() => onSelect(s.stop_id)} onBlur={() => onSelect(null)}>{s.stop_name}</Link>
          <span className="muted tnum">
            {kind === 'sibling'
              ? (s.bearing_from_centroid_deg == null ? 'same spot' : `${formatDistance(s.distance_from_centroid_m)} ${compassWord(s.compass)} of the centre`)
              : `${formatDistance(s.distance_m)} ${compassWord(s.compass)}`}
            {s.route_names?.length ? ` · routes ${s.route_names.slice(0, 4).join(', ')}${s.routes_count > 4 ? ` +${s.routes_count - 4}` : ''}` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}

export { GEOMETRY_MESSAGES };
