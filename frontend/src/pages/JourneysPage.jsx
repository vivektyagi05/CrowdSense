import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { searchJourneys } from '../api/endpoints.js';
import CompareTable from '../features/journeys/CompareTable.jsx';
import JourneyCard from '../features/journeys/JourneyCard.jsx';
import JourneyFilters from '../features/journeys/JourneyFilters.jsx';
import JourneySearchForm from '../features/search/JourneySearchForm.jsx';
import { useAsync } from '../hooks/useAsync.js';
import { useStop } from '../hooks/useStop.js';
import { applyFilters, availableSorts, hasActiveFilters, normalizeJourneys, sortJourneys } from '../lib/journeys.js';
import { isSearchComplete, readSearch, writeSearch } from '../lib/searchParams.js';
import { formatDateLong } from '../lib/time.js';
import { usePageTitle } from '../lib/title.js';
import Button from '../ui/Button.jsx';
import { Select } from '../ui/Field.jsx';
import Icon from '../ui/Icon.jsx';
import Modal from '../ui/Modal.jsx';
import { EmptyState, ErrorState, Notice, Skeleton } from '../ui/States.jsx';
import { useToast } from '../ui/Toast.jsx';

const SERVER_LIMIT = 30;
const MAX_COMPARE = 3;

export default function JourneysPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const search = useMemo(() => readSearch(params), [params]);
  const complete = isSearchComplete(search) && !search.problems.some((p) => p.field === 'departure');
  const departure = search.departure?.value;
  const from = useStop(search.fromId);
  const to = useStop(search.toId);
  usePageTitle(from.stop && to.stop ? `${from.stop.stop_name} to ${to.stop.stop_name}` : 'Journeys');

  const queryKey = complete ? `j:${search.fromId}:${search.toId}:${departure}` : null;
  const result = useAsync(queryKey, (signal) => searchJourneys({ fromId: search.fromId, toId: search.toId, departure, limit: SERVER_LIMIT }, { signal }));
  const ctx = { fromId: search.fromId, toId: search.toId, date: search.departure?.date };
  const all = useMemo(() => (result.data ? normalizeJourneys(result.data, ctx) : []), [result.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const sorts = availableSorts(all);
  const sortKey = sorts.some((s) => s.value === search.sort) ? search.sort : 'earliest';
  const visible = useMemo(() => sortJourneys(applyFilters(all, search.filters), sortKey), [all, search.filters, sortKey]);

  const [compare, setCompare] = useState([]);
  const [compareOpen, setCompareOpen] = useState(false);
  useEffect(() => setCompare([]), [queryKey]);
  const toggleCompare = (id) => setCompare((c) => (c.includes(id) ? c.filter((x) => x !== id) : c.length < MAX_COMPARE ? [...c, id] : c));
  const compared = all.filter((j) => compare.includes(j.id));

  const update = (patch) => setParams(writeSearch({ ...search, departure, ...patch }), { replace: true });
  const newSearch = (s) => setParams(writeSearch(s));
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(window.location.href); notify('Link copied'); } catch { notify('Could not copy the link. Copy it from the address bar.', { tone: 'danger' }); }
  };

  return (
    <div className="container page">
      <div className="page-head">
        <h1>{from.stop && to.stop ? <>{from.stop.stop_name} <span className="page-head__to">to</span> {to.stop.stop_name}</> : 'Journey results'}</h1>
        {search.departure && <p className="muted">Departing after <strong className="tnum">{search.departure.time}</strong> on {formatDateLong(search.departure.date)} (Delhi time)</p>}
      </div>

      <details className="panel edit-search" open={!complete}>
        <summary>Edit search</summary>
        <JourneySearchForm initial={{ fromId: search.fromId, toId: search.toId, departure: search.departure?.value, sort: search.sort }} problems={search.problems} onSubmit={newSearch} onClear={() => navigate('/')} submitLabel="Update search" />
      </details>

      {!complete && <EmptyState title="Choose where you are going">Select an origin and a destination stop and a departure time to see scheduled journeys.</EmptyState>}

      {complete && result.status === 'loading' && <Skeleton lines={6} label="Searching journeys" />}
      {complete && result.status === 'failed' && <ErrorState title="Journey search failed" error={result.error} onRetry={result.retry} />}

      {complete && result.status === 'ready' && (
        <section aria-labelledby="results-title">
          {all.length === 0 ? (
            <NoResults response={result.data} search={search} onFromMidnight={() => newSearch({ fromId: search.fromId, toId: search.toId, departure: `${search.departure.date}T00:00`, sort: search.sort })} />
          ) : (
            <>
              <div className="results-bar">
                <h2 id="results-title" aria-live="polite">
                  {visible.length === all.length ? `${all.length} journey${all.length === 1 ? '' : 's'}` : `${visible.length} of ${all.length} journeys`}
                </h2>
                <div className="results-bar__tools">
                  <Select label="Sort by" value={sortKey} onChange={(e) => update({ sort: e.target.value })} options={sorts} className="results-bar__sort" />
                  <Button variant="secondary" size="sm" onClick={copyLink}><Icon name="link" size={16} />Copy link</Button>
                  <Button variant="secondary" size="sm" disabled={compared.length < 2} onClick={() => setCompareOpen(true)}><Icon name="compare" size={16} />Compare{compared.length ? ` (${compared.length})` : ''}</Button>
                </div>
              </div>
              <p className="muted results-note">
                Scheduled direct buses. The search returns the {SERVER_LIMIT} earliest departures at or after {search.departure.time}{all.length >= SERVER_LIMIT ? '; there may be later ones' : ''}. Filters and sorting apply to these {all.length}.
              </p>
              <JourneyFilters journeys={all} filters={search.filters} onChange={(filters) => update({ filters })} />
              {visible.length === 0 ? (
                <EmptyState title="No journeys match these filters" action={hasActiveFilters(search.filters) && <Button variant="secondary" onClick={() => update({ filters: {} })}>Clear filters</Button>}>
                  {all.length} journey{all.length === 1 ? ' was' : 's were'} returned by the search; the filters hide all of them.
                </EmptyState>
              ) : (
                <ul className="journey-list">
                  {visible.map((j) => (
                    <li key={j.id}>
                      <JourneyCard journey={j} search={ctx} compared={compare.includes(j.id)} compareDisabled={compare.length >= MAX_COMPARE} onToggleCompare={toggleCompare} />
                    </li>
                  ))}
                </ul>
              )}
              {compare.length > 0 && compare.length < 2 && <p className="muted" role="status">Select one more journey to compare (up to {MAX_COMPARE}).</p>}
            </>
          )}
        </section>
      )}

      <Modal open={compareOpen} onClose={() => setCompareOpen(false)} title="Compare journeys" variant="drawer">
        {compared.length >= 2 && <CompareTable journeys={compared} search={ctx} />}
        <p className="muted">Crowd comparison is not possible: historical crowd data is unavailable because ETM passenger data is not connected.</p>
      </Modal>
    </div>
  );
}

/** Explanations here are limited to what the routing response actually says. */
function NoResults({ response, search, onFromMidnight }) {
  const noService = /no active gtfs service/i.test(response?.message ?? '');
  const date = formatDateLong(search.departure.date);
  if (noService) {
    return (
      <EmptyState title="No bus service on this date">
        The timetable has no active service on {date}. Try another date.
      </EmptyState>
    );
  }
  return (
    <EmptyState
      title="No direct bus found"
      action={search.departure.time !== '00:00' && <Button variant="secondary" onClick={onFromMidnight}>Search the whole day</Button>}
    >
      <p>No scheduled direct bus runs between these two stops at or after {search.departure.time} on {date}.</p>
      <p>Only single-bus journeys are searched, so a journey that needs a transfer is not ruled out. {search.departure.time !== '00:00' ? 'Searching from midnight shows whether a direct bus runs on this date at all.' : 'No direct bus runs between them on this date.'}</p>
      <p><Link to="/explore">Explore stops and routes</Link> to find a better pair of stops.</p>
    </EmptyState>
  );
}
