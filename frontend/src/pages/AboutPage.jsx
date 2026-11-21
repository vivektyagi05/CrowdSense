import { Link } from 'react-router-dom';
import { getSummary } from '../api/endpoints.js';
import { useAsync } from '../hooks/useAsync.js';
import { usePageTitle } from '../lib/title.js';
import { StatusBadge } from '../ui/Badges.jsx';
import { ErrorState, Skeleton } from '../ui/States.jsx';

const SCOPE_LABEL = {
  static_schedule: 'Static timetable',
  actual_vehicle_operations: 'Actual vehicle operations',
  passenger_ticket_data: 'Passenger ticket (ETM) data',
  historical_passenger_load: 'Historical passenger load',
  live_crowd_information: 'Live crowd information',
};

export default function AboutPage() {
  usePageTitle('About the data');
  const summary = useAsync('summary', () => getSummary());
  return (
    <div className="container page prose-page">
      <div className="page-head">
        <h1>About CrowdSense and its data</h1>
        <p className="muted">What this product is, what it knows, and what it does not know yet.</p>
      </div>
      <section aria-labelledby="obj"><h2 id="obj">Objective</h2>
        <p>CrowdSense helps passengers find and compare bus journeys in Delhi using reliable schedules and, in time, passenger crowd intelligence: <em>know the crowd before you board.</em></p>
      </section>
      <section aria-labelledby="src"><h2 id="src">Where the data comes from</h2>
        <p>Every stop, route, trip and time comes from a static GTFS feed (General Transit Feed Specification) published for Delhi's buses. It is imported into the backend database and queried live by this app. No journeys, stops or times are written by hand or generated.</p>
      </section>
      <section aria-labelledby="sched"><h2 id="sched">Schedule versus live information</h2>
        <p>A static GTFS feed is the <strong>planned</strong> timetable. It does not say where a bus is now, whether it is late, or whether a trip was cancelled. All times in CrowdSense are scheduled times and are labelled as such. There are no live arrival predictions.</p>
      </section>
      <section aria-labelledby="scope"><h2 id="scope">What is and is not connected</h2>
        {summary.status === 'loading' && <Skeleton lines={4} label="Loading data scope" />}
        {summary.status === 'failed' && <ErrorState title="Data scope unavailable" error={summary.error} onRetry={summary.retry} />}
        {summary.data && (
          <ul className="scope-list">
            {Object.entries(summary.data.data_scope).map(([key, text]) => (
              <li key={key}><StatusBadge tone={text.startsWith('NOT') ? 'warning' : 'success'}>{text.startsWith('NOT') ? 'Not connected' : 'Connected'}</StatusBadge><div><strong>{SCOPE_LABEL[key] ?? key}</strong><p>{text}</p></div></li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="crowd"><h2 id="crowd">Crowd intelligence</h2>
        <p>Historical crowd data unavailable. ETM passenger data not connected. Crowd levels need verified electronic ticketing (ETM) records, which have not been obtained. CrowdSense will not show crowd scores or occupancy until real data supports them.</p>
      </section>
      <section aria-labelledby="lim"><h2 id="lim">Current limitations</h2>
        <ul className="plain-list">
          <li>Journey search finds direct, single-bus journeys. Journeys that need a transfer are not searched yet.</li>
          <li>The search returns the earliest scheduled departures at or after the chosen time on that date.</li>
          <li>Walking connections, fares and real-time disruption are not modelled.</li>
          <li>Many stops share a name; each is a separate stop in the feed, so the stop id and coordinates are shown to tell them apart.</li>
        </ul>
      </section>
      <section aria-labelledby="int"><h2 id="int">Reading the numbers</h2>
        <p>See <Link to="/insights">Network insights</Link> for the size of the feed and its data-quality findings.</p>
      </section>
    </div>
  );
}
