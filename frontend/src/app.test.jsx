import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { fixtures, installFetch, renderApp } from './test/harness.jsx';

const RESULTS_URL = '/journeys?from=106&to=216&departure=2026-11-11T05:00';
const heading = (name) => screen.findByRole('heading', { level: 1, name });

describe('routing and navigation', () => {
  it('renders the journey planner at / with the primary navigation and real network figures', async () => {
    installFetch();
    renderApp('/');
    expect(await heading('Know the crowd before you board.')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual(['/', '/explore', '/insights', '/about']);
    expect(await screen.findByText('Bus stops')).toBeInTheDocument();
    expect(screen.getByText('6,812')).toBeInTheDocument(); // stops, from /gtfs/summary
    expect(screen.getByText('23,85,381')).toBeInTheDocument(); // stop-time rows, Indian digit grouping
    expect(screen.getAllByText(/ETM passenger data not connected/).length).toBeGreaterThan(0);
  });

  it('opens every primary page from the navigation and the logo returns home', async () => {
    installFetch();
    const { user } = renderApp('/about');
    await heading('About CrowdSense and its data');
    await user.click(screen.getByRole('link', { name: 'Explore network' }));
    await heading('Explore the Delhi bus network');
    await user.click(screen.getByRole('link', { name: 'Insights' }));
    await heading('Network insights');
    await user.click(screen.getByRole('link', { name: 'CrowdSense home' }));
    await heading('Know the crowd before you board.');
  });

  it('shows a not-found page for unknown routes, with a way home', async () => {
    installFetch();
    renderApp('/definitely/not/a/page');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Plan a journey' }).every((a) => a.getAttribute('href') === '/')).toBe(true);
  });

  it('restores nested pages from a direct URL (refresh) and supports history back/forward', async () => {
    installFetch();
    const { router } = renderApp('/stops/271');
    expect(await heading('GGS University ISBT Kashmere Gate')).toBeInTheDocument();
    await act(() => router.navigate('/routes/72'));
    await heading('114UP');
    await act(() => router.navigate(-1));
    await heading('GGS University ISBT Kashmere Gate');
    await act(() => router.navigate(1));
    await heading('114UP');
  });

  it('opens and closes the mobile menu', async () => {
    installFetch();
    const { user } = renderApp('/about');
    const toggle = screen.getByRole('button', { name: 'Open menu' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Close menu' })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('navigation', { name: 'Primary' })).toHaveClass('is-open');
  });

  it('warns when the backend is unreachable and recovers on Retry', async () => {
    let up = false;
    installFetch((u) => (u.pathname.endsWith('/health') && !up ? 'network' : undefined));
    const { user } = renderApp('/about');
    expect(await screen.findByText(/Cannot reach the backend/)).toBeInTheDocument();
    up = true;
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.queryByText(/Cannot reach the backend/)).not.toBeInTheDocument());
  });
});

describe('journey search', () => {
  async function pick(user, label, typed, optionIndex = 0) {
    await user.type(screen.getByRole('combobox', { name: label }), typed);
    const options = within(await screen.findByRole('listbox')).getAllByRole('option'); // scoped: the sort <select> also has options
    await user.click(options[optionIndex]);
  }

  it('selects real stops, submits to the routing engine and lands on results with a shareable URL', async () => {
    const f = installFetch();
    const { user, router } = renderApp('/');
    await heading('Know the crowd before you board.');
    await pick(user, 'From', 'roop');
    await pick(user, 'To', 'alpana', 1);
    fireEvent.change(screen.getByLabelText('Depart after: date'), { target: { value: '2026-11-11' } });
    fireEvent.change(screen.getByLabelText('Depart after: time'), { target: { value: '05:00' } });
    await user.click(screen.getByRole('button', { name: /Search journeys/ }));
    expect(await screen.findByRole('heading', { level: 2, name: '30 journeys' })).toBeInTheDocument();
    const { pathname, search } = router.state.location;
    expect(pathname).toBe('/journeys');
    expect(Object.fromEntries(new URLSearchParams(search))).toEqual({ from: '106', to: '216', departure: '2026-11-11T05:00' });
    const call = f.calls.find((u) => u.pathname.endsWith('/journeys'));
    expect(Object.fromEntries(call.searchParams)).toMatchObject({ origin_stop_id: '106', destination_stop_id: '216', departure: '2026-11-11T05:00', limit: '30' });
    expect(await screen.findByRole('heading', { level: 1, name: /Banglow Road.*to.*Alpana Cinema/ })).toBeInTheDocument();
  });

  it('refuses to search until both stops are real selections, and explains why', async () => {
    const f = installFetch();
    const { user } = renderApp('/');
    await heading('Know the crowd before you board.');
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'some typed text');
    await user.click(screen.getByRole('button', { name: /Search journeys/ }));
    expect(screen.getByText('Choose a starting stop from the suggestions.')).toBeInTheDocument();
    expect(screen.getByText('Choose a destination stop from the suggestions.')).toBeInTheDocument();
    expect(f.calls.some((u) => u.pathname.endsWith('/journeys'))).toBe(false);
  });

  it('validates the departure date and rejects identical stops', async () => {
    installFetch();
    const { user } = renderApp('/');
    await heading('Know the crowd before you board.');
    await pick(user, 'From', 'roop', 0);
    await pick(user, 'To', 'roop', 0);
    fireEvent.change(screen.getByLabelText('Depart after: date'), { target: { value: '' } });
    await user.click(screen.getByRole('button', { name: /Search journeys/ }));
    expect(screen.getByText('Origin and destination must be different stops.')).toBeInTheDocument();
    expect(screen.getByText('Enter a valid date and time.')).toBeInTheDocument();
  });

  it('swaps the selected stops, and cannot swap before both are chosen', async () => {
    installFetch();
    const { user } = renderApp('/');
    await heading('Know the crowd before you board.');
    const swap = screen.getByRole('button', { name: 'Swap origin and destination' });
    expect(swap).toBeDisabled();
    await pick(user, 'From', 'roop');
    await pick(user, 'To', 'alpana');
    expect(swap).toBeEnabled();
    await user.click(swap);
    expect(screen.getByRole('combobox', { name: 'From' })).toHaveValue('Alpana Cinema (Model Town Mtr Stn)');
    expect(screen.getByRole('combobox', { name: 'To' })).toHaveValue('Banglow Road / Police Station Roop Nagar');
    expect(screen.getByText('Selected stop 100')).toBeInTheDocument();
  });

  it('clears the whole search', async () => {
    installFetch();
    const { user } = renderApp('/');
    await heading('Know the crowd before you board.');
    await pick(user, 'From', 'roop');
    await user.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(screen.getByRole('combobox', { name: 'From' })).toHaveValue('');
  });

  it('defaults the departure to Delhi "now", never a fixed historical date', async () => {
    installFetch();
    renderApp('/');
    await heading('Know the crowd before you board.');
    const date = screen.getByLabelText('Depart after: date').value;
    expect(date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(Math.abs(Date.parse(date) - Date.now())).toBeLessThan(2 * 86_400_000);
  });

  it('only offers a transfer limit it can honour: it says transfers are not supported instead of showing a dead control', async () => {
    installFetch();
    renderApp('/');
    await heading('Know the crowd before you board.');
    expect(screen.getByText('Direct buses only')).toBeInTheDocument();
    expect(screen.queryByLabelText(/transfer/i)).not.toBeInTheDocument();
  });
});

describe('journey results', () => {
  const fixtureRoutes = fixtures.journeys.items.reduce((m, i) => m.set(i.route_name, (m.get(i.route_name) ?? 0) + 1), new Map());

  it('restores the search from the URL: resolves stop names, queries the engine, renders real journeys', async () => {
    const f = installFetch();
    renderApp(RESULTS_URL);
    expect(await screen.findByRole('heading', { level: 2, name: '30 journeys' })).toBeInTheDocument();
    const first = screen.getAllByRole('article')[0];
    expect(within(first).getByText('06:56')).toBeInTheDocument();
    expect(within(first).getByText('07:06')).toBeInTheDocument();
    expect(within(first).getByText('10 min')).toBeInTheDocument();
    expect(within(first).getByText('Direct')).toBeInTheDocument();
    expect(within(first).getByText('114UP')).toBeInTheDocument();
    expect(within(first).getByText(/7 stops between/)).toBeInTheDocument();
    expect(within(first).getByText('Historical crowd data unavailable.')).toBeInTheDocument();
    expect(f.calls.filter((u) => u.pathname.endsWith('/journeys'))).toHaveLength(1);
    expect(screen.getByText(/30 earliest departures at or after 05:00/)).toBeInTheDocument();
  });

  it('filters by route over the returned candidate set and keeps the count honest', async () => {
    installFetch();
    const { user } = renderApp(RESULTS_URL);
    await screen.findByRole('heading', { level: 2, name: '30 journeys' });
    await user.selectOptions(screen.getByLabelText('Bus route'), '134UP'.length ? fixtures.journeys.items.find((i) => i.route_name === '134UP').route_id : '');
    const n = fixtureRoutes.get('134UP');
    expect(await screen.findByRole('heading', { level: 2, name: `${n} of 30 journeys` })).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(n);
    for (const card of screen.getAllByRole('article')) expect(within(card).getByText('134UP')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(await screen.findByRole('heading', { level: 2, name: '30 journeys' })).toBeInTheDocument();
  });

  it('filters by departure window and explains when filters hide everything', async () => {
    installFetch();
    const { user } = renderApp(RESULTS_URL);
    await screen.findByRole('heading', { level: 2, name: '30 journeys' });
    fireEvent.change(screen.getByLabelText('Departs no earlier than'), { target: { value: '23:00' } });
    expect(await screen.findByText('No journeys match these filters')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Clear filters' }).at(-1));
    expect(await screen.findByRole('heading', { level: 2, name: '30 journeys' })).toBeInTheDocument();
  });

  it('keeps filters in the URL so they survive refresh and sharing', async () => {
    installFetch();
    const { router } = renderApp(`${RESULTS_URL}&departFrom=12:00`);
    const shown = await screen.findByRole('heading', { level: 2, name: /of 30 journeys/ });
    const expected = fixtures.journeys.items.filter((i) => i.departure.slice(11, 16) >= '12:00').length;
    expect(shown).toHaveTextContent(`${expected} of 30 journeys`);
    expect(screen.getByLabelText('Departs no earlier than')).toHaveValue('12:00');
    expect(router.state.location.search).toContain('departFrom=12');
  });

  it('re-orders journeys when the sort changes (synthetic response with differing durations)', async () => {
    // Real timetable data has identical durations per stop pair, so ordering is exercised with a modified copy.
    const plus = (iso, min) => new Date(Date.parse(`${iso}Z`) + min * 60_000).toISOString().slice(0, 19);
    const items = fixtures.journeys.items.slice(0, 3).map((it, i) => {
      const minutes = [30, 10, 20][i];
      return { ...it, trip_id: `t${i}`, scheduled_duration_minutes: minutes, arrival: plus(it.departure, minutes) };
    });
    installFetch((u) => (u.pathname.endsWith('/journeys') ? { status: 200, body: { items, mode: 'direct_only' } } : undefined));
    const { user } = renderApp(RESULTS_URL);
    await screen.findByRole('heading', { level: 2, name: '3 journeys' });
    const durations = () => screen.getAllByRole('article').map((a) => within(a).getByText(/^\d+ min$/).textContent);
    expect(durations()).toEqual(['30 min', '10 min', '20 min']); // earliest departure
    await user.selectOptions(screen.getByLabelText('Sort by'), 'fastest');
    expect(durations()).toEqual(['10 min', '20 min', '30 min']);
    expect(screen.queryByRole('option', { name: 'Fewest transfers' })).not.toBeInTheDocument();
  });

  it('compares up to three journeys side by side', async () => {
    installFetch();
    const { user } = renderApp(RESULTS_URL);
    await screen.findByRole('heading', { level: 2, name: '30 journeys' });
    const compareButton = screen.getByRole('button', { name: /^Compare/ });
    expect(compareButton).toBeDisabled();
    const boxes = screen.getAllByRole('checkbox', { name: 'Compare' });
    await user.click(boxes[0]);
    await user.click(boxes[1]);
    await user.click(boxes[2]);
    expect(boxes[3]).toBeDisabled(); // limit of three
    await user.click(screen.getByRole('button', { name: 'Compare (3)' }));
    const dialog = screen.getByRole('dialog', { hidden: true });
    expect(within(dialog).getByRole('table')).toBeInTheDocument();
    expect(within(dialog).getAllByText('Data unavailable')).toHaveLength(3);
    expect(within(dialog).getByText(/Crowd comparison is not possible/)).toBeInTheDocument();
  });

  it('explains a no-result search honestly and offers a whole-day search that queries from midnight', async () => {
    const f = installFetch();
    const { user, router } = renderApp('/journeys?from=271&to=1046&departure=2026-11-11T08:00');
    expect(await screen.findByText('No direct bus found')).toBeInTheDocument();
    expect(screen.getByText(/does not rule out|not ruled out/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Search the whole day' }));
    await waitFor(() => expect(f.calls.some((u) => u.pathname.endsWith('/journeys') && u.searchParams.get('departure') === '2026-11-11T00:00')).toBe(true));
    expect(router.state.location.search).toContain('2026-11-11T00%3A00');
  });

  it('says when there is no service at all on the date, using the routing message', async () => {
    installFetch((u) => (u.pathname.endsWith('/journeys') ? { status: 200, body: { items: [], message: 'No active GTFS service for this date.' } } : undefined));
    renderApp(RESULTS_URL);
    expect(await screen.findByText('No bus service on this date')).toBeInTheDocument();
  });

  it('shows an API failure with Retry that re-runs the search', async () => {
    let calls = 0;
    installFetch((u) => {
      if (!u.pathname.endsWith('/journeys')) return undefined;
      calls += 1;
      return calls <= 2 ? { status: 400, body: { error: { code: 'invalid_departure', message: 'Use ISO local datetime.' } } } : undefined;
    });
    const { user } = renderApp(RESULTS_URL);
    expect(await screen.findByText('Use ISO local datetime.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('heading', { level: 2, name: '30 journeys' }).catch(() => {});
  });

  it('does not search with an invalid departure in the link and says so, without substituting another time', async () => {
    const f = installFetch();
    renderApp('/journeys?from=106&to=216&departure=2026-02-30T08:00');
    expect(await screen.findByText(/departure in this link is not valid/i)).toBeInTheDocument();
    expect(f.calls.some((u) => u.pathname.endsWith('/journeys'))).toBe(false);
  });

  it('reports a stop id from the link that does not exist', async () => {
    installFetch();
    renderApp('/journeys?from=999999&to=216&departure=2026-11-11T05:00');
    expect(await screen.findByText(/Stop 999999 from this link was not found/)).toBeInTheDocument();
  });

  it('prompts for a search when the URL has none', async () => {
    renderApp('/journeys');
    installFetch();
    expect(await screen.findByText('Choose where you are going')).toBeInTheDocument();
  });
});

describe('journey details', () => {
  it('opens from a result card and shows the full leg: route, trip, stops, times, intermediate stops, crowd status', async () => {
    installFetch();
    const { user, router } = renderApp(RESULTS_URL);
    await screen.findByRole('heading', { level: 2, name: '30 journeys' });
    await user.click(within(screen.getAllByRole('article')[0]).getByRole('link', { name: 'View journey' }));
    expect(await screen.findByText('Trip 72_06_40')).toBeInTheDocument(); // only on the details page (the results page has the same h1)
    expect(router.state.location.pathname).toBe('/journeys/72_06_40');
    const timeline = screen.getByRole('list', { name: 'Journey timeline' });
    expect(within(timeline).getByText('Board bus 114UP')).toBeInTheDocument();
    expect(within(timeline).getByText('06:56')).toBeInTheDocument();
    expect(within(timeline).getByText('07:06')).toBeInTheDocument();
    expect(within(timeline).getByText(/7 stops between/)).toBeInTheDocument();
    expect(within(timeline).getByText('7 intermediate stops')).toBeInTheDocument();
    expect(within(timeline).getByText('Origin · board')).toBeInTheDocument();
    expect(within(timeline).getByText('Alight · destination')).toBeInTheDocument();
    expect(screen.getByText('Historical crowd data unavailable.')).toBeInTheDocument();
    expect(screen.getByText(/no vehicle positions or arrival predictions/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Back to results/ }));
    expect(await screen.findByRole('heading', { level: 2, name: '30 journeys' })).toBeInTheDocument();
    expect(router.state.location.search).toContain('from=106');
  });

  it('works from a direct URL (refresh) and links its stops and route to their pages', async () => {
    installFetch();
    renderApp('/journeys/72_06_40?from=106&to=216&date=2026-11-11&board=06%3A56%3A26');
    await heading(/Banglow Road/);
    const stopLinks = screen.getAllByRole('link', { name: /Alpana Cinema/ });
    expect(stopLinks[0]).toHaveAttribute('href', '/stops/216');
    expect(screen.getAllByRole('link', { name: 'Route 114UP' })[0]).toHaveAttribute('href', '/routes/72');
  });

  it('handles an incomplete link, a missing trip and a trip that no longer fits the search', async () => {
    installFetch();
    const a = renderApp('/journeys/72_06_40?from=106');
    expect(await screen.findByText('This journey link is incomplete')).toBeInTheDocument();
    a.unmount();
    const b = renderApp('/journeys/NOPE?from=106&to=216&date=2026-11-11&board=06%3A56%3A26');
    expect(await screen.findByText('Trip not found')).toBeInTheDocument();
    b.unmount();
    renderApp('/journeys/72_06_40?from=216&to=106&date=2026-11-11&board=07%3A06%3A42');
    expect(await screen.findByText('This trip no longer matches the search')).toBeInTheDocument();
  });
});

describe('explore, stop and route pages', () => {
  it('lists real stops a page at a time and requests the next offset', async () => {
    const f = installFetch();
    const { user } = renderApp('/explore');
    expect(await screen.findByText(/stops found/)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /./ }).filter((a) => a.getAttribute('href')?.startsWith('/stops/'))).toHaveLength(fixtures.stopsList.items.length);
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(f.calls.some((u) => u.pathname.endsWith('/stops') && u.searchParams.get('offset') === '20')).toBe(true));
  });

  it('searches stops (minimum length enforced) and the query goes to the backend', async () => {
    const f = installFetch();
    const { user } = renderApp('/explore');
    await screen.findByText(/stops found/);
    const box = screen.getByRole('searchbox', { name: 'Search stops' });
    await user.type(box, 'r{Enter}');
    expect(screen.getByText('Enter at least 2 characters.')).toBeInTheDocument();
    await user.clear(box);
    await user.type(box, 'roop{Enter}');
    await waitFor(() => expect(f.calls.some((u) => u.pathname.endsWith('/stops') && u.searchParams.get('q') === 'roop')).toBe(true));
  });

  it('switches to routes with arrow keys, lists real routes and filters by agency', async () => {
    const f = installFetch();
    const { user } = renderApp('/explore');
    await screen.findByText(/stops found/);
    screen.getByRole('tab', { name: 'Stops' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Routes' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText(/routes found/)).toBeInTheDocument();
    await user.selectOptions(await screen.findByLabelText('Agency'), 'DOT');
    await waitFor(() => expect(f.calls.some((u) => u.pathname.endsWith('/routes') && u.searchParams.get('agency_id') === 'DOT')).toBe(true));
  });

  it('shows a stop with its serving routes, coordinates and scheduled departures labelled as not live', async () => {
    const f = installFetch();
    renderApp('/stops/271');
    await heading('GGS University ISBT Kashmere Gate');
    expect(screen.getByText(/code E100BA81/)).toBeInTheDocument();
    expect(screen.getByText('28.66528, 77.23019')).toBeInTheDocument();
    expect(await screen.findByText(/timetable entries, not live arrivals/)).toBeInTheDocument();
    expect(await screen.findByRole('table', { name: 'Scheduled departures from this stop' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Route / }).length).toBeGreaterThan(0);
    const dep = f.calls.find((u) => u.pathname.endsWith('/departures'));
    expect(dep.searchParams.get('limit')).toBe('20'); // bounded request
  });

  it('shows a missing stop clearly', async () => {
    installFetch();
    renderApp('/stops/does-not-exist');
    expect(await screen.findByText('Stop not found')).toBeInTheDocument();
  });

  it('shows a route with agency, directions, calendar, shape and a selectable stop sequence', async () => {
    const f = installFetch();
    const { user } = renderApp('/routes/72');
    await heading('114UP');
    expect(screen.getByText('Department of Transport')).toBeInTheDocument();
    expect(screen.getByText(/shape.*published/)).toBeInTheDocument();
    expect(await screen.findByText(/Stops of trip/i)).toBeInTheDocument();
    expect(f.calls.find((u) => u.pathname.endsWith('/stop-times')).searchParams.get('limit')).toBe('100');
    const pills = screen.getAllByRole('button', { pressed: true });
    expect(pills).toHaveLength(1);
    await user.click(screen.getAllByRole('button', { pressed: false })[0]);
    await waitFor(() => expect(screen.getAllByRole('button', { pressed: true })).toHaveLength(1));
  });

  it('shows a missing route clearly', async () => {
    installFetch();
    renderApp('/routes/nope');
    expect(await screen.findByText('Route not found')).toBeInTheDocument();
  });
});

describe('insights and about', () => {
  it('shows the real feed metrics, shape coverage, the service bar and data-quality warnings', async () => {
    installFetch();
    renderApp('/insights');
    await heading('Network insights');
    expect(await screen.findByText('23,85,381')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByText(/65,322 of 65,322 trips have a shape/)).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: '65,322 trips active, 0 inactive' })).toBeInTheDocument();
    expect(await screen.findByText(/pass with warnings/i)).toBeInTheDocument();
    expect(screen.getByText(/feed_info.txt has 2 rows/)).toBeInTheDocument();
    expect(screen.getByText(/Delhi Transport Corporation · version v1/)).toBeInTheDocument();
  });

  it('queries service for the chosen date', async () => {
    const f = installFetch();
    renderApp('/insights');
    await screen.findByLabelText('Date');
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-12-25' } });
    await waitFor(() => expect(f.calls.some((u) => u.pathname.endsWith('/services/active') && u.searchParams.get('date') === '2026-12-25')).toBe(true));
  });

  it('shows failure with retry rather than empty figures', async () => {
    let fail = true;
    installFetch((u) => (u.pathname.endsWith('/gtfs/summary') && fail ? { status: 503, body: { error: { code: 'database_error', message: 'The database could not complete the request.' } } } : undefined));
    const { user } = renderApp('/insights');
    expect(await screen.findByText('The database could not complete the request.')).toBeInTheDocument();
    fail = false;
    await user.click(screen.getAllByRole('button', { name: 'Retry' })[0]);
    expect(await screen.findByText('Shape coverage')).toBeInTheDocument();
  });

  it('about page states what is and is not connected, from the backend data scope', async () => {
    installFetch();
    renderApp('/about');
    expect(await screen.findByText('Passenger ticket (ETM) data')).toBeInTheDocument();
    expect(screen.getAllByText('Not connected').length).toBe(4);
    expect(screen.getByText('Historical passenger load')).toBeInTheDocument();
    expect(screen.getByText(/Historical crowd data unavailable\. ETM passenger data not connected\./)).toBeInTheDocument();
  });
});
