import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getAllTripStopTimes, getRoute, getRouteShapeGeometry, getSummary, getTripStopTimes, listRouteTrips } from '../api/endpoints.js';
import { routeMapData, toMapStops } from '../lib/geo.js';
import { useAsync } from '../hooks/useAsync.js';
import { formatGtfsDate, formatNumber, parseGtfsTime } from '../lib/time.js';
import { usePageTitle } from '../lib/title.js';
import { RouteBadge, StatusBadge } from '../ui/Badges.jsx';
import Button from '../ui/Button.jsx';
import Pagination from '../ui/Pagination.jsx';
import { EmptyState, ErrorState, Skeleton } from '../ui/States.jsx';
import Stat from '../ui/Stat.jsx';

const LazyMapView = lazy(() => import('../features/map/LazyMapView.jsx'));
const TRIP_PAGE = 15;
const STOP_PAGE = 100;
const ROUTE_TYPES = { 3: 'Bus' };

export default function RouteDetailPage() {
  const { routeId } = useParams();
  const route = useAsync(`route:${routeId}`, (signal) => getRoute(routeId, { signal }));
  const summary = useAsync('summary', () => getSummary());
  const name = route.data?.route_short_name || route.data?.route_long_name;
  usePageTitle(name ? `Route ${name}` : 'Route');

  if (route.status === 'loading') return <div className="container page"><Skeleton lines={6} label="Loading route" /></div>;
  if (route.status === 'failed') {
    return (
      <div className="container page">
        {route.error.status === 404 ? <EmptyState title="Route not found" action={<Button to="/explore?tab=routes">Explore routes</Button>}>{route.error.message}</EmptyState> : <ErrorState title="Could not load this route" error={route.error} onRetry={route.retry} />}
      </div>
    );
  }
  const r = route.data;
  const withShape = r.shapes.filter((s) => s.point_count);
  const dirs = Object.entries(r.directions);
  const cal = summary.data?.calendar;
  return (
    <div className="container page">
      <div className="page-head">
        <p><RouteBadge id={r.route_id} name={name} to={null} /></p>
        <h1>{r.route_long_name || name}</h1>
        {r.route_desc && <p className="muted">{r.route_desc}</p>}
      </div>
      <dl className="stat-grid">
        <Stat label="Agency" value={<span className="stat__small">{r.agency?.agency_name ?? 'Not specified'}</span>} />
        <Stat label="Type" value={<span className="stat__small">{ROUTE_TYPES[r.route_type] ?? `GTFS type ${r.route_type}`}</span>} />
        <Stat label="Trips" value={formatNumber(r.trip_count)} />
        <Stat label="Distinct stops" value={formatNumber(r.stop_count)} />
      </dl>
      <section className="panel" aria-labelledby="facts-title">
        <h2 id="facts-title">Service and geometry</h2>
        <ul className="plain-list">
          <li><strong>Directions:</strong> {dirs.map(([d, n]) => `${d === 'unspecified' ? 'Direction not specified' : `Direction ${d}`}: ${n} trip${n === 1 ? '' : 's'}`).join('; ')}.</li>
          <li><strong>Service calendar:</strong> {r.service_ids.length ? `service ${r.service_ids.join(', ')}` : 'no service'}{cal ? `, defined from ${formatGtfsDate(cal.first_start_date)} to ${formatGtfsDate(cal.last_end_date)}${cal.calendar_dates_present ? '' : ', with no date exceptions'}` : ''}.</li>
          <li><strong>Shape:</strong> {withShape.length ? <StatusBadge tone="success">{withShape.length} shape{withShape.length === 1 ? '' : 's'} published</StatusBadge> : <StatusBadge tone="warning">No shape published</StatusBadge>} {withShape.length > 0 && <span className="muted tnum">({withShape.map((s) => `${s.shape_id}: ${formatNumber(s.point_count)} points`).join('; ')}).</span>}</li>
        </ul>
      </section>
      <Trips route={r} />
    </div>
  );
}

function Trips({ route }) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(null);
  const [listedTrip, setListedTrip] = useState(null);   // the text list of this trip has loaded -> now the map may load
  const trips = useAsync(`trips:${route.route_id}:${offset}`, (signal) => listRouteTrips(route.route_id, { limit: TRIP_PAGE, offset }, { signal }), { keepPrevious: true });
  useEffect(() => { if (trips.data?.items.length && !trips.data.items.some((t) => t.trip_id === selected)) setSelected(trips.data.items[0].trip_id); }, [trips.data]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="panel" aria-labelledby="trips-title">
      <h2 id="trips-title">Trips and stop sequence</h2>
      {trips.status === 'failed' && <ErrorState title="Could not load trips" error={trips.error} onRetry={trips.retry} />}
      {!trips.data && trips.status === 'loading' && <Skeleton lines={4} label="Loading trips" />}
      {trips.data && (
        <>
          <p className="muted">Choose a trip to see the stops it calls at. Timetables differ between trips; this page does not assume one pattern.</p>
          <ul className="trip-list" aria-label="Trips">
            {trips.data.items.map((t) => (
              <li key={t.trip_id}>
                <button type="button" className="trip-pill" aria-pressed={t.trip_id === selected} onClick={() => setSelected(t.trip_id)}>
                  <span className="tnum">{parseGtfsTime(t.first_departure)?.clock ?? '—'}</span>
                  <span className="muted">{t.trip_headsign || `Trip ${t.trip_id}`}</span>
                </button>
              </li>
            ))}
          </ul>
          <Pagination offset={offset} limit={TRIP_PAGE} total={trips.data.total} onChange={setOffset} itemLabel="trips" />
          {selected && <StopSequence tripId={selected} onLoaded={() => setListedTrip(selected)} />}
          {selected && listedTrip === selected && <RouteMap routeId={route.route_id} tripId={selected} />}
        </>
      )}
    </section>
  );
}

function StopSequence({ tripId, onLoaded }) {
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [tripId]);
  const r = useAsync(`seq:${tripId}:${offset}`, (signal) => getTripStopTimes(tripId, { limit: STOP_PAGE, offset }, { signal }), { keepPrevious: true });
  useEffect(() => { if (r.status === 'ready') onLoaded?.(); }, [r.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (r.status === 'failed') return <ErrorState title="Could not load the stop sequence" error={r.error} onRetry={r.retry} />;
  if (!r.data) return <Skeleton lines={5} label="Loading stop sequence" />;
  return (
    <div className="stop-sequence">
      <h3>Stops of trip <span className="tnum">{tripId}</span></h3>
      <ol className="seq" start={offset + 1}>
        {r.data.items.map((s) => (
          <li key={s.stop_sequence}>
            <span className="tnum seq__time">{parseGtfsTime(s.arrival_time || s.departure_time)?.clock ?? ''}</span>
            <Link to={`/stops/${encodeURIComponent(s.stop_id)}`}>{s.stop_name}</Link>
          </li>
        ))}
      </ol>
      <Pagination offset={offset} limit={STOP_PAGE} total={r.data.total} onChange={setOffset} itemLabel="stops" />
    </div>
  );
}


function RouteMap({ routeId, tripId }) {
  const shapes = useAsync(`rshapes:${routeId}`, (signal) => getRouteShapeGeometry(routeId, {}, { signal }));
  const times = useAsync(`rstops:${tripId}`, (signal) => getAllTripStopTimes(tripId, { signal }));
  const [pickedShape, setPickedShape] = useState(null);
  const [selectedStop, setSelectedStop] = useState(null);
  const items = shapes.data?.items ?? [];
  const shapeItem = items.find((s) => s.shape_id === pickedShape) ?? items.find((s) => s.geometry_status === 'ok') ?? items[0];
  const stops = useMemo(() => toMapStops(times.data?.items ?? []), [times.data]);
  const data = useMemo(() => routeMapData({ shapeItem: shapes.status === 'ready' ? shapeItem : undefined, stops }), [shapes.status, shapeItem, stops]);
  const fallback = useMemo(() => stops.map((s) => ({ id: `${s.id}-${s.sequence}`, name: s.name, href: `/stops/${encodeURIComponent(s.id)}` })), [stops]);
  const picked = selectedStop ? stops.find((s) => s.id === selectedStop) : null;
  return (
    <div className="route-map">
      <h3>Route path and stops of trip <span className="tnum">{tripId}</span></h3>
      {items.length > 1 && (
        <div role="group" aria-label="Route shapes" className="trip-list">
          {items.map((s) => <button key={s.shape_id} type="button" className="trip-pill" aria-pressed={s.shape_id === shapeItem?.shape_id} onClick={() => setPickedShape(s.shape_id)}><span className="tnum">{s.shape_id}</span><span className="muted">{s.trip_count} trip{s.trip_count === 1 ? '' : 's'}</span></button>)}
        </div>
      )}
      {(shapes.status === 'loading' || times.status === 'loading') && <p className="muted" role="status">Loading the route path and stops…</p>}
      {shapes.status === 'failed' && <ErrorState title="Could not load the route path" error={shapes.error} onRetry={shapes.retry} />}
      {times.status === 'failed' && <ErrorState title="Could not load the stops of this trip" error={times.error} onRetry={times.retry} />}
      {times.status === 'ready' && (
        <Suspense fallback={<Skeleton lines={4} label="Loading map" />}>
          <LazyMapView label={`Map of route ${routeId}`} data={data} fallbackStops={fallback} selectedStopId={selectedStop} onSelectStop={setSelectedStop} />
        </Suspense>
      )}
      {shapes.status === 'ready' && data.message && <p className="map-geo-note" role="status">{data.message}</p>}
      {shapes.status === 'ready' && data.line && <p className="muted">Path drawn from the published GTFS shape {shapeItem.shape_id} ({shapeItem.point_count_returned} of {shapeItem.point_count_original} points, within {shapeItem.tolerance_m} m).</p>}
      {shapeItem && stops.length > 0 && !items.some((s) => s.shape_id === shapeItem.shape_id) && null}
      {picked && <p className="stop-callout"><span className="stop-callout__name">{picked.name}</span><Link to={`/stops/${encodeURIComponent(picked.id)}`}>Open stop page</Link></p>}
    </div>
  );
}
