import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { listAgencies, listRoutes, searchStops } from '../api/endpoints.js';
import { useAsync } from '../hooks/useAsync.js';
import { formatNumber } from '../lib/time.js';
import { usePageTitle } from '../lib/title.js';
import { RouteBadge } from '../ui/Badges.jsx';
import Button from '../ui/Button.jsx';
import { Input, Select } from '../ui/Field.jsx';
import Icon from '../ui/Icon.jsx';
import Pagination from '../ui/Pagination.jsx';
import { EmptyState, ErrorState, Skeleton } from '../ui/States.jsx';
import { TabPanel, Tabs } from '../ui/Tabs.jsx';

const PAGE_SIZE = 20;
const TABS = [{ id: 'stops', label: 'Stops' }, { id: 'routes', label: 'Routes' }];

/** State lives in the URL (tab, q, agency, page) so lists are shareable and back/forward works. */
export default function ExplorePage() {
  usePageTitle('Explore the network');
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'routes' ? 'routes' : 'stops';
  const q = params.get('q') ?? '';
  const agency = params.get('agency') ?? '';
  const offset = Math.max(0, Number.parseInt(params.get('offset') ?? '0', 10) || 0);
  const patch = (p, { reset = true } = {}) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(p)) (v ? next.set(k, v) : next.delete(k));
    if (reset) next.delete('offset');
    setParams(next);
  };

  return (
    <div className="container page">
      <div className="page-head">
        <h1>Explore the Delhi bus network</h1>
        <p className="muted">Browse the stops and routes in the timetable. Every list is read from the backend a page at a time.</p>
      </div>
      <Tabs tabs={TABS} value={tab} idPrefix="explore" label="Network" onChange={(id) => setParams(id === 'routes' ? { tab: 'routes' } : {})} />
      <TabPanel id="stops" value={tab} idPrefix="explore"><StopsList q={q} offset={offset} patch={patch} /></TabPanel>
      <TabPanel id="routes" value={tab} idPrefix="explore"><RoutesList q={q} agency={agency} offset={offset} patch={patch} /></TabPanel>
    </div>
  );
}

function SearchBar({ q, patch, label, min = 0, children }) {
  const [text, setText] = useState(q);
  const [error, setError] = useState('');
  useEffect(() => setText(q), [q]);
  const submit = (e) => {
    e.preventDefault();
    const t = text.trim();
    if (t && t.length < min) { setError(`Enter at least ${min} characters.`); return; }
    setError('');
    patch({ q: t });
  };
  return (
    <form className="explore-search" onSubmit={submit} role="search" aria-label={label}>
      <Input label={label} type="search" value={text} onChange={(e) => setText(e.target.value)} error={error} placeholder="Search by name" />
      {children}
      <Button type="submit"><Icon name="search" size={18} />Search</Button>
      {q && <Button variant="ghost" onClick={() => patch({ q: '' })}>Clear</Button>}
    </form>
  );
}

function StopsList({ q, offset, patch }) {
  const r = useAsync(`stops:${q}:${offset}`, (signal) => searchStops({ q: q || undefined, limit: PAGE_SIZE, offset }, { signal }), { keepPrevious: true });
  return (
    <>
      <SearchBar q={q} patch={patch} label="Search stops" min={2} />
      <ResultArea r={r} empty={`No stops match “${q}”.`} itemLabel="stops" offset={offset} onPage={(o) => patch({ offset: o ? String(o) : '' }, { reset: false })}>
        {(items) => (
          <ul className="list">
            {items.map((s) => (
              <li key={s.stop_id} className="list__row">
                <Icon name="pin" size={18} />
                <div><Link to={`/stops/${encodeURIComponent(s.stop_id)}`} className="list__title">{s.stop_name}</Link><p className="muted tnum">Stop {s.stop_id} · {s.stop_lat.toFixed(4)}, {s.stop_lon.toFixed(4)}</p></div>
              </li>
            ))}
          </ul>
        )}
      </ResultArea>
    </>
  );
}

function RoutesList({ q, agency, offset, patch }) {
  const agencies = useAsync('agencies', () => listAgencies());
  const r = useAsync(`routes:${q}:${agency}:${offset}`, (signal) => listRoutes({ q: q || undefined, agencyId: agency || undefined, limit: PAGE_SIZE, offset }, { signal }), { keepPrevious: true });
  const list = agencies.data?.items ?? [];
  return (
    <>
      <SearchBar q={q} patch={patch} label="Search routes">
        {list.length > 1 && <Select label="Agency" value={agency} onChange={(e) => patch({ agency: e.target.value })} options={[{ value: '', label: 'All agencies' }, ...list.map((a) => ({ value: a.agency_id, label: a.agency_name }))]} />}
      </SearchBar>
      <ResultArea r={r} empty="No routes match this search." itemLabel="routes" offset={offset} onPage={(o) => patch({ offset: o ? String(o) : '' }, { reset: false })}>
        {(items) => (
          <ul className="list">
            {items.map((rt) => (
              <li key={rt.route_id} className="list__row">
                <RouteBadge id={rt.route_id} name={rt.route_short_name || rt.route_id} />
                <div><Link to={`/routes/${encodeURIComponent(rt.route_id)}`} className="list__title">{rt.route_long_name || rt.route_short_name}</Link>{rt.route_desc && <p className="muted">{rt.route_desc}</p>}</div>
              </li>
            ))}
          </ul>
        )}
      </ResultArea>
    </>
  );
}

function ResultArea({ r, empty, itemLabel, offset, onPage, children }) {
  if (r.status === 'failed') return <ErrorState title="Could not load the list" error={r.error} onRetry={r.retry} />;
  if (!r.data) return <Skeleton lines={6} label="Loading list" />;
  if (r.data.items.length === 0) return <EmptyState title="Nothing found">{empty}</EmptyState>;
  return (
    <div aria-busy={r.status === 'loading'} className={r.status === 'loading' ? 'is-stale' : ''}>
      <p className="muted tnum results-note">{formatNumber(r.data.total)} {itemLabel} found</p>
      {children(r.data.items)}
      <Pagination offset={offset} limit={r.data.limit} total={r.data.total} onChange={onPage} itemLabel={itemLabel} />
    </div>
  );
}
