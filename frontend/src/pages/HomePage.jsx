import { Link, useNavigate } from 'react-router-dom';
import { getSummary } from '../api/endpoints.js';
import JourneySearchForm from '../features/search/JourneySearchForm.jsx';
import { useAsync } from '../hooks/useAsync.js';
import { formatGtfsDate, formatNumber } from '../lib/time.js';
import { writeSearch } from '../lib/searchParams.js';
import { usePageTitle } from '../lib/title.js';
import { StatusBadge } from '../ui/Badges.jsx';
import { ErrorState, Skeleton } from '../ui/States.jsx';
import Stat from '../ui/Stat.jsx';

export default function HomePage() {
  usePageTitle('');
  const navigate = useNavigate();
  const summary = useAsync('summary', () => getSummary());
  const submit = (search) => navigate(`/journeys?${writeSearch(search)}`);

  return (
    <div className="container page">
      <section className="hero" aria-labelledby="hero-title">
        <h1 id="hero-title">Know the crowd before you board.</h1>
        <p className="hero__lead">Plan Delhi bus journeys from the published timetable. Crowd levels will join the schedule once verified passenger data is connected.</p>
      </section>

      <section className="panel panel--search" aria-labelledby="search-title">
        <h2 id="search-title" className="sr-only">Search journeys</h2>
        <JourneySearchForm onSubmit={submit} />
        <p className="muted nearby-entry">Not sure which stop? <Link to="/nearby">Find stops near you or near a point on the map</Link>.</p>
      </section>

      <section className="network-facts" aria-labelledby="facts-title">
        <h2 id="facts-title">What this planner is built on</h2>
        {summary.status === 'loading' && <Skeleton lines={3} label="Loading network facts" />}
        {summary.status === 'failed' && <ErrorState title="Network facts unavailable" error={summary.error} onRetry={summary.retry} />}
        {summary.status === 'ready' && (
          <>
            <dl className="stat-grid">
              <Stat label="Bus stops" value={formatNumber(summary.data.counts.stops)} />
              <Stat label="Routes" value={formatNumber(summary.data.counts.routes)} />
              <Stat label="Scheduled trips" value={formatNumber(summary.data.counts.trips)} />
              <Stat label="Stop calls" value={formatNumber(summary.data.counts.stop_times)} note="scheduled stop-time records" />
            </dl>
            <ul className="status-list">
              <li><StatusBadge tone="success">Connected</StatusBadge> Static GTFS timetable, {summary.data.agencies.map((a) => a.agency_name).join(' and ')}, valid {formatGtfsDate(summary.data.calendar.first_start_date)} to {formatGtfsDate(summary.data.calendar.last_end_date)}.</li>
              <li><StatusBadge tone="warning">Not connected</StatusBadge> Crowd data. ETM passenger data not connected.</li>
              <li><StatusBadge tone="warning">Not connected</StatusBadge> Live bus locations and arrival predictions.</li>
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
