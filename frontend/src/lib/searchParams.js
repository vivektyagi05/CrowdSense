// The journey search lives in the URL so it can be shared, refreshed and restored with browser history.
import { DEFAULT_SORT, isSortKey } from './journeys.js';
import { parseDeparture } from './time.js';

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

/**
 * Parse URL params into a search + filters. Invalid values are *reported* in `problems`, never silently replaced:
 * a bad departure stays unset so the form shows the error instead of quietly searching another time.
 */
export function readSearch(params) {
  const problems = [];
  const fromId = params.get('from')?.trim() || '';
  const toId = params.get('to')?.trim() || '';
  const rawDeparture = params.get('departure');
  let departure = null;
  if (rawDeparture) {
    const parsed = parseDeparture(rawDeparture);
    if (parsed.ok) departure = parsed;
    else problems.push({ field: 'departure', message: `The departure in this link is not valid. ${parsed.reason}` });
  }
  if (fromId && toId && fromId === toId) problems.push({ field: 'to', message: 'Origin and destination must be different stops.' });

  const rawSort = params.get('sort');
  let sort = DEFAULT_SORT;
  if (rawSort) {
    if (isSortKey(rawSort)) sort = rawSort;
    else problems.push({ field: 'sort', message: `Unknown ordering "${rawSort}"; showing earliest departures first.` });
  }

  const maxDurationRaw = params.get('maxDuration');
  const maxDuration = maxDurationRaw && /^\d{1,3}$/.test(maxDurationRaw) ? Number(maxDurationRaw) : null;
  const filters = {
    route: params.get('route') || '',
    maxDuration,
    departFrom: HHMM.test(params.get('departFrom') ?? '') ? params.get('departFrom') : '',
    departTo: HHMM.test(params.get('departTo') ?? '') ? params.get('departTo') : '',
  };
  return { fromId, toId, departure, sort, filters, problems };
}

/** Serialise a search (+ optional filters) into a query string; empty values are omitted. */
export function writeSearch({ fromId, toId, departure, sort, filters = {} }) {
  const q = new URLSearchParams();
  if (fromId) q.set('from', fromId);
  if (toId) q.set('to', toId);
  if (departure) q.set('departure', departure);
  if (sort && sort !== DEFAULT_SORT) q.set('sort', sort);
  if (filters.route) q.set('route', filters.route);
  if (filters.maxDuration != null) q.set('maxDuration', String(filters.maxDuration));
  if (filters.departFrom) q.set('departFrom', filters.departFrom);
  if (filters.departTo) q.set('departTo', filters.departTo);
  return q.toString();
}

export const isSearchComplete = (s) => Boolean(s.fromId && s.toId && s.departure && s.fromId !== s.toId);
