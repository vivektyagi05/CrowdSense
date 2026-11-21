import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { getAllTripStopTimes, getLegShape, getTrip } from '../api/endpoints.js';
import BottomSheet from '../features/map/BottomSheet.jsx';
import LazyMapView from '../features/map/LazyMapView.jsx';
import { legMapData } from '../lib/geo.js';
import CrowdStatus from '../features/journeys/CrowdStatus.jsx';
import JourneyTimeline from '../features/journeys/JourneyTimeline.jsx';
import { useAsync } from '../hooks/useAsync.js';
import { buildLeg } from '../lib/journeyDetail.js';
import { formatDateLong, formatDuration } from '../lib/time.js';
import { usePageTitle } from '../lib/title.js';
import { RouteBadge, StatusBadge } from '../ui/Badges.jsx';
import Button from '../ui/Button.jsx';
import { EmptyState, ErrorState, Skeleton } from '../ui/States.jsx';
import Stat from '../ui/Stat.jsx';

const HHMMSS = /^\d{2}:\d{2}:\d{2}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export default function JourneyDetailPage() {
  const { tripId } = useParams();
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const fromId = params.get('from') ?? '';
  const toId = params.get('to') ?? '';
  const date = params.get('date') ?? '';
  const board = params.get('board') ?? '';
  const valid = fromId && toId && DATE.test(date) && HHMMSS.test(board);
  usePageTitle('Journey details');

  const data = useAsync(valid ? `jd:${tripId}` : null, (signal) => Promise.all([getTrip(tripId, { signal }), getAllTripStopTimes(tripId, { signal })]));
  const built = useMemo(() => {
    if (!data.data) return null;
    const [trip, times] = data.data;
    return { trip, ...buildLeg({ stopTimes: times.items, trip, fromId, toId, board }) };
  }, [data.data, fromId, toId, board]);

  const backTo = `/journeys?${new URLSearchParams({ from: fromId, to: toId, departure: `${date}T${board.slice(0, 5)}` })}`;
  const back = () => (location.state?.fromResults ? navigate(-1) : navigate(backTo));

  if (!valid) {
    return (
      <div className="container page">
        <EmptyState title="This journey link is incomplete" action={<Button to="/">Plan a journey</Button>}>
          A journey link needs the origin and destination stops, the service date and the boarding time. Search again to get a complete link.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="container page">
      <p><button type="button" className="link-btn" onClick={back}>← Back to results</button></p>
      {data.status === 'loading' && <Skeleton lines={8} label="Loading journey" />}
      {data.status === 'failed' && (
        data.error.status === 404
          ? <EmptyState title="Trip not found" action={<Button to="/">Plan a journey</Button>}>{data.error.message}</EmptyState>
          : <ErrorState title="Could not load this journey" error={data.error} onRetry={data.retry} />
      )}
      {built?.error && (
        <EmptyState title="This trip no longer matches the search" action={<Link to={backTo}>Back to the search</Link>}>
          {built.error === 'origin_not_on_trip' ? 'The origin stop is not served by this trip.' : 'This trip does not reach the destination after the origin.'}
        </EmptyState>
      )}
      {built?.leg && <Detail leg={built.leg} date={date} fromId={fromId} toId={toId} board={board} />}
    </div>
  );
}

function Detail({ leg, date, fromId, toId, board }) {
  const first = leg.stops[0];
  const last = leg.stops[leg.stops.length - 1];
  const [active, setActive] = useState(null);       // stop id highlighted from the timeline (hover/focus) or the map (click)
  const shape = useAsync(`leg:${leg.tripId}:${first.id}:${last.id}:${board}`, (signal) => getLegShape({ tripId: leg.tripId, fromId: first.id, toId: last.id, board }, { signal }));
  const mapData = useMemo(() => {
    if (shape.status === 'loading' || shape.status === 'idle') return legMapData({ shape: { status: 'loading' }, stops: leg.stops, boardId: first.id, alightId: last.id });
    return legMapData({ shape: shape.status === 'ready' ? shape.data : { status: 'failed' }, stops: leg.stops, boardId: first.id, alightId: last.id });
  }, [shape.status, shape.data, leg.stops, first.id, last.id]);
  const loading = shape.status === 'loading';
  const activeStop = active ? leg.stops.find((s) => s.id === active) : null;
  const fallbackStops = useMemo(() => leg.stops.map((s) => ({ id: `${s.id}-${s.sequence}`, name: s.name, href: `/stops/${encodeURIComponent(s.id)}` })), [leg.stops]);
  return (
    <>
      <div className="page-head">
        <h1>{first.name} <span className="page-head__to">to</span> {last.name}</h1>
        <p className="muted">Scheduled journey on {formatDateLong(date)} (Delhi time). Times are from the static timetable, not live.</p>
      </div>
      <div className="map-layout">
        <div className="map-layout__map">
          <LazyMapView label={`Map of the ${leg.routeName} journey from ${first.name} to ${last.name}`} data={mapData} fallbackStops={fallbackStops} selectedStopId={active} onSelectStop={setActive} />
          {loading && <p className="muted map-geo-note" role="status">Loading the route path…</p>}
          {!loading && mapData.message && (
            <p className="map-geo-note" role="status">
              {mapData.message}{' '}
              {shape.status === 'failed' && <button type="button" className="link-btn" onClick={shape.retry}>Retry</button>}
            </p>
          )}
          {!loading && mapData.line && <p className="muted map-geo-note" style={{ color: 'inherit', background: 'transparent', padding: 0 }}>Path drawn from the published GTFS shape ({shape.data.point_count_returned} points, simplified within {shape.data.tolerance_m} m).</p>}
          {activeStop && (
            <p className="stop-callout">
              <span className="stop-callout__name">{activeStop.name}</span>
              <Link to={`/stops/${encodeURIComponent(activeStop.id)}`}>Open stop page</Link>
            </p>
          )}
        </div>
        <BottomSheet title={`${leg.routeName} · ${first.time} → ${last.time}`}>
          <section className="summary" aria-label="Journey summary">
            <dl className="stat-grid">
              <Stat label="Departs" value={<>{first.time}</>} />
              <Stat label="Arrives" value={<>{last.time}{last.dayOffset ? <sup>+{last.dayOffset}</sup> : null}</>} />
              <Stat label="Duration" value={formatDuration(leg.durationMinutes)} />
              <Stat label="Transfers" value="0" note="direct" />
            </dl>
            <p className="summary__route"><RouteBadge id={leg.routeId} name={leg.routeName} /> <StatusBadge tone="neutral">Trip {leg.tripId}</StatusBadge> <span className="muted">Service {leg.serviceId}</span></p>
          </section>
          <section className="panel" aria-labelledby="tl-title">
            <h2 id="tl-title">Your journey</h2>
            <JourneyTimeline legs={[leg]} activeStopId={active} onActiveStop={setActive} />
            <p className="muted timeline-note">Walking to the first stop and from the last stop is not included, and no vehicle positions or arrival predictions are available.</p>
          </section>
          <section aria-label="Crowd information"><CrowdStatus crowd={null} variant="full" /></section>
        </BottomSheet>
      </div>
    </>
  );
}
