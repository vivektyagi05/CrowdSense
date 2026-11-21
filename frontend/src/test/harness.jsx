import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import { routes } from '../App.jsx';

import health from './fixtures/health.json';
import summary from './fixtures/summary.json';
import validation from './fixtures/validation.json';
import agencies from './fixtures/agencies.json';
import stopsSearchRoop from './fixtures/stops-search-roop.json';
import stopsSearchAlpana from './fixtures/stops-search-alpana.json';
import journeys from './fixtures/journeys-106-216.json';
import journeysEmpty from './fixtures/journeys-empty.json';
import stop106 from './fixtures/stop-106.json';
import stop216 from './fixtures/stop-216.json';
import stop271 from './fixtures/stop-271.json';
import departures271 from './fixtures/departures-271.json';
import trip72 from './fixtures/trip-72.json';
import stoptimes72 from './fixtures/stoptimes-72.json';
import route72 from './fixtures/route-72.json';
import route72Trips from './fixtures/route-72-trips.json';
import routesList from './fixtures/routes-list.json';
import stopsList from './fixtures/stops-list.json';
import servicesActive from './fixtures/services-active.json';

// Every fixture below is a response recorded from the real backend running on the real Delhi GTFS import.
export const fixtures = {
  health, summary, validation, agencies, stopsSearchRoop, stopsSearchAlpana, journeys, journeysEmpty,
  stop106, stop216, stop271, departures271, trip72, stoptimes72, route72, route72Trips, routesList, stopsList, servicesActive,
};

const json = (body, status = 200) => ({ status, body });
const notFound = (what) => json({ error: { code: 'not_found', message: `Unknown ${what}.` }, detail: `Unknown ${what}.` }, 404);

/** Default fake backend: answers like the real API for the recorded requests. Override per test with `overrides`. */
export function defaultHandler(url) {
  const path = url.pathname.replace(/^\/api\/v1/, '');
  const q = url.searchParams;
  if (path === '/health') return json(health);
  if (path === '/gtfs/summary') return json(summary);
  if (path === '/gtfs/validation-report') return json(validation);
  if (path === '/agencies') return json(agencies);
  if (path === '/services/active') return json(servicesActive);
  if (path === '/stops') {
    const term = q.get('q');
    if (!term) return json({ ...stopsList, offset: Number(q.get('offset') ?? 0) });
    if (term.startsWith('roop')) return json(stopsSearchRoop);
    if (term.startsWith('alpana')) return json(stopsSearchAlpana);
    return json({ items: [], total: 0, limit: 8, offset: 0 });
  }
  const stops = { 106: stop106, 216: stop216, 271: stop271 };
  let m = /^\/stops\/([^/]+)$/.exec(path);
  if (m) return stops[m[1]] ? json(stops[m[1]]) : notFound(`stop ${m[1]}`);
  if (/^\/stops\/[^/]+\/departures$/.test(path)) return json(departures271);
  if (path === '/journeys') return q.get('origin_stop_id') === '106' ? json(journeys) : json(journeysEmpty);
  if (path === '/trips/72_06_40') return json(trip72);
  if (path === '/trips/72_06_40/stop-times') return json(stoptimes72);
  if (/^\/trips\//.test(path)) return notFound('trip');
  if (path === '/routes') return json({ ...routesList, offset: Number(q.get('offset') ?? 0) });
  if (path === '/routes/72') return json(route72);
  if (path === '/routes/72/trips') return json(route72Trips);
  if (/^\/routes\//.test(path)) return notFound('route');
  return notFound(path);
}

/** Installs a fetch stub. `handler(url)` may return {status, body}, undefined (fall through) or throw/return 'network'. */
export function installFetch(handler = () => undefined) {
  const calls = [];
  const stub = vi.fn((input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    calls.push(url);
    return new Promise((resolve, reject) => {
      const respond = () => {
        let result;
        try { result = handler(url, calls) ?? defaultHandler(url); } catch (err) { reject(err); return; }
        if (result === 'network') { reject(new TypeError('Failed to fetch')); return; }
        if (result && typeof result.then === 'function') { result.then((r) => resolve(toResponse(r)), reject); return; }
        resolve(toResponse(result));
      };
      if (init.signal?.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
      respond();
    });
  });
  vi.stubGlobal('fetch', stub);
  return { calls, stub, paths: () => calls.map((u) => u.pathname.replace('/api/v1', '') + u.search) };
}

function toResponse({ status, body }) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

export function renderApp(path = '/') {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const user = userEvent.setup();
  const utils = render(<RouterProvider router={router} />);
  return { router, user, ...utils };
}
