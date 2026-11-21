import { lazy, Suspense, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getStopDepartures } from '../api/endpoints.js';
import { useAsync } from '../hooks/useAsync.js';
import { useStop } from '../hooks/useStop.js';
import { clockOf, delhiNow, formatDateLong, formatNumber } from '../lib/time.js';
import { usePageTitle } from '../lib/title.js';
import SaveToggle from '../features/places/SaveToggle.jsx';
import { RouteBadge } from '../ui/Badges.jsx';
import Button from '../ui/Button.jsx';
import { DateTimeField } from '../ui/Field.jsx';
import { EmptyState, ErrorState, Notice, Skeleton } from '../ui/States.jsx';
import Stat from '../ui/Stat.jsx';

const StopAround = lazy(() => import('../features/map/StopAround.jsx'));
const ROUTE_PREVIEW = 24;
const PAGE = 20;
const MAX_DEPARTURES = 100;

export default function StopDetailPage() {
  const { stopId } = useParams();
  const { stop, status, error, retry } = useStop(stopId);
  usePageTitle(stop?.stop_name ?? 'Stop');
  const [showAllRoutes, setShowAllRoutes] = useState(false);

  if (status === 'loading') return <div className="container page"><Skeleton lines={6} label="Loading stop" /></div>;
  if (status === 'failed') {
    return (
      <div className="container page">
        {error.status === 404 ? <EmptyState title="Stop not found" action={<Button to="/explore">Explore stops</Button>}>{error.message}</EmptyState> : <ErrorState title="Could not load this stop" error={error} onRetry={retry} />}
      </div>
    );
  }
  if (!stop) return null;
  const routes = showAllRoutes ? stop.routes : stop.routes.slice(0, ROUTE_PREVIEW);
  return (
    <div className="container page">
      <div className="page-head">
        <h1>{stop.stop_name}</h1>
        <p className="muted tnum">Stop {stop.stop_id}{stop.stop_code ? ` · code ${stop.stop_code}` : ''}</p>
        <p><SaveToggle stopId={stop.stop_id} /></p>
      </div>
      <dl className="stat-grid">
        <Stat label="Coordinates" value={<span className="stat__small">{stop.stop_lat.toFixed(5)}, {stop.stop_lon.toFixed(5)}</span>} />
        <Stat label="Routes serving" value={formatNumber(stop.routes.length)} />
        <Stat label="Scheduled calls" value={formatNumber(stop.stop_time_count)} note="all trips, all days" />
        {stop.parent_station && <Stat label="Parent station" value={<Link to={`/stops/${encodeURIComponent(stop.parent_station)}`}>{stop.parent_station}</Link>} />}
      </dl>
      <section className="panel" aria-labelledby="routes-title">
        <h2 id="routes-title">Routes serving this stop</h2>
        {stop.routes.length === 0 ? <p className="muted">No route calls at this stop.</p> : (
          <ul className="chips">
            {routes.map((r) => <li key={r.route_id}><RouteBadge id={r.route_id} name={r.route_short_name || r.route_long_name || r.route_id} /></li>)}
          </ul>
        )}
        {stop.routes.length > ROUTE_PREVIEW && <Button variant="ghost" size="sm" onClick={() => setShowAllRoutes((v) => !v)}>{showAllRoutes ? 'Show fewer routes' : `Show all ${stop.routes.length} routes`}</Button>}
      </section>
      {Number.isFinite(stop.stop_lat) && Number.isFinite(stop.stop_lon) && <Suspense fallback={<Skeleton lines={4} label="Loading map" />}><StopAround stop={stop} /></Suspense>}
      <Departures stopId={stop.stop_id} />
    </div>
  );
}

function Departures({ stopId }) {
  const [when, setWhen] = useState(() => { const n = delhiNow(); return `${n.date}T${n.time}`; });
  const [limit, setLimit] = useState(PAGE);
  const [date, time] = when.split('T');
  const valid = Boolean(date && time);
  const r = useAsync(valid ? `dep:${stopId}:${when}:${limit}` : null, (signal) => getStopDepartures(stopId, { date, after: time, limit }, { signal }), { keepPrevious: true });
  const items = r.data?.items ?? [];
  return (
    <section className="panel" aria-labelledby="dep-title">
      <h2 id="dep-title">Scheduled departures</h2>
      <Notice tone="info">These are timetable entries, not live arrivals. Buses may run early, late or not at all.</Notice>
      <div className="dep-controls"><DateTimeField label="From" value={when} onChange={(v) => { setWhen(v); setLimit(PAGE); }} /></div>
      {valid && <p className="muted">Service date context: showing departures on {formatDateLong(date)} at or after {time}. Entries marked “previous service day” belong to a trip that started the day before and runs past midnight.</p>}
      {r.status === 'failed' && <ErrorState title="Could not load departures" error={r.error} onRetry={r.retry} />}
      {!r.data && r.status === 'loading' && <Skeleton lines={5} label="Loading departures" />}
      {r.data && items.length === 0 && <EmptyState title="No scheduled departures">No timetable departures from this stop at or after {time} on {formatDateLong(date)}.</EmptyState>}
      {items.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <caption className="sr-only">Scheduled departures from this stop</caption>
            <thead><tr><th scope="col">Time</th><th scope="col">Route</th><th scope="col">Towards</th><th scope="col">Service day</th></tr></thead>
            <tbody>
              {items.map((d) => (
                <tr key={`${d.trip_id}-${d.stop_sequence}`}>
                  <td className="tnum"><strong>{clockOf(d.departure)}</strong></td>
                  <td><RouteBadge id={d.route_id} name={d.route_short_name || d.route_long_name || d.route_id} /></td>
                  <td>{d.trip_headsign || <span className="muted">Not published</span>}</td>
                  <td className="muted tnum">{d.service_date === date ? 'This date' : `Previous service day (${d.service_date})`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {items.length >= limit && limit < MAX_DEPARTURES && <Button variant="secondary" onClick={() => setLimit((l) => Math.min(MAX_DEPARTURES, l + PAGE))} loading={r.status === 'loading'}>Show more departures</Button>}
    </section>
  );
}
