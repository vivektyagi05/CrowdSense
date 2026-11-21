import { useState } from 'react';
import { getActiveServices, getSummary, getValidationReport } from '../api/endpoints.js';
import { useAsync } from '../hooks/useAsync.js';
import { delhiNow, formatDateLong, formatGtfsDate, formatNumber } from '../lib/time.js';
import { usePageTitle } from '../lib/title.js';
import { StatusBadge } from '../ui/Badges.jsx';
import { DateTimeField } from '../ui/Field.jsx';
import { ErrorState, Notice, Skeleton } from '../ui/States.jsx';
import Stat from '../ui/Stat.jsx';

const SEVERITY = { error: { tone: 'danger', rank: 0 }, warning: { tone: 'warning', rank: 1 }, info: { tone: 'neutral', rank: 2 } };

export default function InsightsPage() {
  usePageTitle('Network insights');
  const summary = useAsync('summary', () => getSummary());
  const report = useAsync('report', () => getValidationReport());
  return (
    <div className="container page">
      <div className="page-head">
        <h1>Network insights</h1>
        <p className="muted">Figures calculated by the backend from the imported timetable. Nothing here is estimated.</p>
      </div>
      {summary.status === 'loading' && <Skeleton lines={5} label="Loading network figures" />}
      {summary.status === 'failed' && <ErrorState title="Network figures unavailable" error={summary.error} onRetry={summary.retry} />}
      {summary.data && <Figures s={summary.data} />}
      <ServiceDay />
      {summary.data && <FeedMetadata s={summary.data} />}
      <section className="panel" aria-labelledby="dq-title">
        <h2 id="dq-title">Data quality</h2>
        {report.status === 'loading' && <Skeleton lines={4} label="Loading data-quality report" />}
        {report.status === 'failed' && <ErrorState title="Data-quality report unavailable" error={report.error} onRetry={report.retry} />}
        {report.data && <Quality report={report.data} />}
      </section>
    </div>
  );
}

function Figures({ s }) {
  const { counts, shapes } = s;
  const coverage = shapes.trips_total ? Math.round((shapes.trips_with_shape / shapes.trips_total) * 1000) / 10 : null;
  return (
    <section aria-labelledby="fig-title">
      <h2 id="fig-title" className="sr-only">Feed totals</h2>
      <dl className="stat-grid stat-grid--5">
        <Stat label="Stops" value={formatNumber(counts.stops)} />
        <Stat label="Routes" value={formatNumber(counts.routes)} />
        <Stat label="Trips" value={formatNumber(counts.trips)} />
        <Stat label="Stop-time records" value={formatNumber(counts.stop_times)} note="scheduled calls" />
        <Stat label="Shape coverage" value={coverage == null ? 'n/a' : `${coverage}%`} note={`${formatNumber(shapes.trips_with_shape)} of ${formatNumber(shapes.trips_total)} trips have a shape`} />
      </dl>
    </section>
  );
}

function ServiceDay() {
  const [when, setWhen] = useState(() => `${delhiNow().date}T00:00`);
  const date = when.split('T')[0];
  const r = useAsync(date ? `svc:${date}` : null, (signal) => getActiveServices({ date, includeInactive: true }, { signal }));
  const active = r.data?.services.filter((x) => x.active).reduce((a, x) => a + x.trip_count, 0) ?? 0;
  const inactive = r.data?.services.filter((x) => !x.active).reduce((a, x) => a + x.trip_count, 0) ?? 0;
  const total = active + inactive;
  return (
    <section className="panel" aria-labelledby="svc-title">
      <h2 id="svc-title">Service on a date</h2>
      <div className="dep-controls">
        <label className="field__label" htmlFor="svc-date">Date</label>
        <input id="svc-date" className="control" type="date" value={date} onChange={(e) => setWhen(`${e.target.value}T00:00`)} />
      </div>
      {r.status === 'loading' && <Skeleton lines={2} label="Loading service calendar" />}
      {r.status === 'failed' && <ErrorState title="Could not load the service calendar" error={r.error} onRetry={r.retry} />}
      {r.data && total > 0 && (
        <figure className="bar-figure">
          <figcaption>Trips running on {formatDateLong(r.data.date)}: <strong className="tnum">{formatNumber(active)}</strong> of <span className="tnum">{formatNumber(total)}</span> scheduled trips ({r.data.active_count} active service{r.data.active_count === 1 ? '' : 's'}, {r.data.inactive_count} inactive).</figcaption>
          <div className="bar" role="img" aria-label={`${formatNumber(active)} trips active, ${formatNumber(inactive)} inactive`}>
            <span className="bar__on" style={{ width: `${(active / total) * 100}%` }} />
          </div>
          <div className="bar-legend"><span><i className="swatch swatch--on" /> Active</span><span><i className="swatch swatch--off" /> Not running</span></div>
        </figure>
      )}
      {r.data && !r.data.calendar_dates_present && <p className="muted">The feed has no calendar exceptions (holidays or special days), so every date follows the weekly pattern.</p>}
    </section>
  );
}

function FeedMetadata({ s }) {
  return (
    <section className="panel" aria-labelledby="meta-title">
      <h2 id="meta-title">Feed metadata</h2>
      <dl className="meta">
        {s.feed.map((f) => (
          <div key={f.feed_info_id}><dt>Publisher</dt><dd>{f.feed_publisher_name} · version {f.feed_version} · valid {formatGtfsDate(f.feed_start_date)} to {formatGtfsDate(f.feed_end_date)}</dd></div>
        ))}
        <div><dt>Agencies</dt><dd>{s.agencies.map((a) => a.agency_name).join(', ')}</dd></div>
        <div><dt>Imported</dt><dd className="tnum">{s.imported_at}</dd></div>
        <div><dt>Source file</dt><dd>{s.source_zip_name}<span className="muted tnum"> · SHA-256 {s.source_sha256?.slice(0, 12)}…</span></dd></div>
      </dl>
    </section>
  );
}

function Quality({ report }) {
  const dq = report.data_quality;
  const findings = [...(dq?.findings ?? [])].sort((a, b) => (SEVERITY[a.severity]?.rank ?? 9) - (SEVERITY[b.severity]?.rank ?? 9));
  return (
    <>
      <p><StatusBadge tone={dq?.error_count ? 'danger' : dq?.warning_count ? 'warning' : 'success'}>{dq?.status?.replaceAll('_', ' ')}</StatusBadge> <span className="tnum">{dq?.error_count} errors · {dq?.warning_count} warnings · {dq?.info_count} notes</span></p>
      {findings.length === 0 && <Notice tone="success">No findings were recorded.</Notice>}
      <ul className="findings">
        {findings.map((f, i) => (
          <li key={`${f.code}-${i}`}><StatusBadge tone={SEVERITY[f.severity]?.tone}>{f.severity}</StatusBadge> <span>{f.message}</span></li>
        ))}
      </ul>
    </>
  );
}
