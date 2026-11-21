import { screen, waitFor, within } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installFetch, renderApp } from '../test/harness.jsx';

const probe = vi.hoisted(() => ({ props: null }));
vi.mock('../features/map/LazyMapView.jsx', () => ({
  default: (props) => { probe.props = props; return <div data-testid="map-probe" data-origin={props.data.origin ? 'yes' : 'no'} data-ring={props.data.accuracy ? 'yes' : 'no'} data-count={props.data.stops.features.length} />; },
}));

const nearbyBody = (items, extra = {}) => ({ radius_m: 500, limit: 30, total_in_radius: items.length, returned: items.length, index: 'rtree', data_basis: 'gtfs_stops', notice: 'Distances are straight-line', items, ...extra });
const item = (id, name, d, compass = 'N', routes = ['101', '202']) => ({ stop_id: id, stop_name: name, stop_lat: 28.61 + d / 1e5, stop_lon: 77.21, distance_m: d, bearing_deg: 0, compass, routes_count: routes.length, route_names: routes, cluster_id: null });
const ITEMS = [item('A', 'Alpha Chowk', 40), item('B', 'Beta Mor', 120, 'E', ['9']), item('C', 'Gamma Gate', 300, 'SW')];
const handler = (items = ITEMS) => (u) => (u.pathname.endsWith('/stops/nearby') ? { status: 200, body: nearbyBody(items) } : undefined);

let getCurrentPosition;
const setGeo = (impl) => {
  getCurrentPosition = vi.fn(impl);
  Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition }, configurable: true });
};
const grant = (accuracy = 25) => (ok) => ok({ coords: { latitude: 28.6101234, longitude: 77.2102345, accuracy } });
const fail = (code) => (_ok, err) => err({ code });
const nearbyCalls = (f) => f.calls.filter((u) => u.pathname.endsWith('/stops/nearby'));

beforeEach(() => { probe.props = null; localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { delete navigator.geolocation; });

describe('nearby page', () => {
  it('never prompts for location or calls the API until the button is pressed', async () => {
    setGeo(grant());
    const f = installFetch(handler());
    renderApp('/nearby');
    expect(await screen.findByRole('heading', { name: 'Stops near you' })).toBeInTheDocument();
    expect(screen.getByText(/Nothing is requested until you do/)).toBeInTheDocument();
    expect(getCurrentPosition).not.toHaveBeenCalled();
    expect(nearbyCalls(f)).toHaveLength(0);
  });

  it('granted: requests the position once, lists stops in the server (distance) order with real distances, and draws the point', async () => {
    setGeo(grant(25));
    const f = installFetch(handler());
    const { user } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    const list = await screen.findByRole('list', { name: 'Nearby stops' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map((r) => within(r).getAllByRole('link')[0].textContent)).toEqual(['Alpha Chowk', 'Beta Mor', 'Gamma Gate']);
    expect(rows[0]).toHaveTextContent('40 m north');
    expect(rows[2]).toHaveTextContent('300 m south-west');
    expect(rows[1]).toHaveTextContent('routes 9');
    expect(within(rows[0]).getAllByRole('link')[0]).toHaveAttribute('href', '/stops/A');
    const call = nearbyCalls(f)[0];
    expect(call.searchParams.get('lat')).toBe('28.6101234'); expect(call.searchParams.get('lon')).toBe('77.2102345');
    expect(call.searchParams.get('radius_m')).toBe('500');
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(getCurrentPosition.mock.calls[0][2]).toMatchObject({ maximumAge: 0, timeout: 10000 });     // never a cached position
    expect(screen.getByTestId('map-probe')).toHaveAttribute('data-origin', 'yes');
    expect(screen.getByTestId('map-probe')).toHaveAttribute('data-count', '3');
    expect(screen.queryByText(/only accurate to about/)).not.toBeInTheDocument();
  });

  it('warns when accuracy is worse than 200 m and shows the accuracy ring', async () => {
    setGeo(grant(850));
    installFetch(handler());
    const { user } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    expect(await screen.findByText(/only accurate to about 850 m/)).toBeInTheDocument();
    expect(screen.getByTestId('map-probe')).toHaveAttribute('data-ring', 'yes');
  });

  it.each([[1, /permission was denied/], [2, /could not determine a location/], [3, /took too long/], [99, /Something went wrong/]])('geolocation error code %i: clear message, no request, the map pick still works', async (code, msg) => {
    setGeo(fail(code));
    const f = installFetch(handler());
    const { user } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    expect(await screen.findByText(msg)).toBeInTheDocument();
    expect(nearbyCalls(f)).toHaveLength(0);
    await act(async () => probe.props.onPickPoint({ lat: 28.62, lon: 77.22 }));      // fallback path
    expect(await screen.findByRole('list', { name: 'Nearby stops' })).toBeInTheDocument();
    expect(screen.queryByText(msg)).not.toBeInTheDocument();
  });

  it('browser without a geolocation API: says so immediately', async () => {
    delete navigator.geolocation;
    installFetch(handler());
    renderApp('/nearby');
    expect(await screen.findByText(/could not determine a location/)).toBeInTheDocument();
  });

  it('radius control really changes the request', async () => {
    setGeo(grant());
    const f = installFetch(handler());
    const { user } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    await screen.findByRole('list', { name: 'Nearby stops' });
    await user.selectOptions(screen.getByRole('combobox', { name: 'Search radius' }), '2000');
    await waitFor(() => expect(nearbyCalls(f).map((u) => u.searchParams.get('radius_m'))).toEqual(['500', '2000']));
    expect(screen.getByRole('combobox', { name: 'Search radius' })).toHaveValue('2000');
  });

  it('pick on map: a tapped point is searched; the user must still choose a real stop (a point is never a stop)', async () => {
    setGeo(grant());
    const f = installFetch(handler());
    const { router } = renderApp('/nearby');
    await screen.findByTestId('map-probe');
    await act(async () => probe.props.onPickPoint({ lat: 28.6, lon: 77.2 }));
    expect(await screen.findByRole('list', { name: 'Nearby stops' })).toBeInTheDocument();
    expect(nearbyCalls(f)[0].searchParams.get('lat')).toBe('28.6');
    expect(router.state.location.search).toBe('');                                   // nothing chosen yet
    expect(screen.queryByText('Journey so far:')).not.toBeInTheDocument();
    expect(getCurrentPosition).not.toHaveBeenCalled();
  });

  it('a tapped point outside Delhi-NCR is refused locally with no request', async () => {
    setGeo(grant());
    const f = installFetch(handler());
    renderApp('/nearby');
    await screen.findByTestId('map-probe');
    await act(async () => probe.props.onPickPoint({ lat: 19.07, lon: 72.87 }));
    expect(await screen.findByText(/outside the Delhi-NCR area/)).toBeInTheDocument();
    expect(nearbyCalls(f)).toHaveLength(0);
  });

  it('use as origin / destination fill the journey with REAL stop ids only, then continue to the journey search', async () => {
    setGeo(grant());
    installFetch(handler());
    const { user, router } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    const rows = within(await screen.findByRole('list', { name: 'Nearby stops' })).getAllByRole('listitem');
    await user.click(within(rows[0]).getByRole('button', { name: 'Use as origin' }));
    await user.click(within(rows[2]).getByRole('button', { name: 'Use as destination' }));
    expect(router.state.location.search).toBe('?from=A&to=C');
    expect(within(rows[0]).getByRole('button', { name: 'Use as origin' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/Journey so far:/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Continue to journey search' }));
    expect(router.state.location.pathname).toBe('/journeys');
    expect(new URLSearchParams(router.state.location.search).get('from')).toBe('A');
    expect(new URLSearchParams(router.state.location.search).get('to')).toBe('C');
  });

  it('same stop as origin and destination is flagged and cannot continue', async () => {
    setGeo(grant());
    installFetch(handler());
    const { user } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    const row = within(await screen.findByRole('list', { name: 'Nearby stops' })).getAllByRole('listitem')[0];
    await user.click(within(row).getByRole('button', { name: 'Use as origin' }));
    await user.click(within(row).getByRole('button', { name: 'Use as destination' }));
    expect(screen.getByText('Origin and destination must be different stops.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue to journey search' })).toBeDisabled();
  });

  it('the position is never persisted: not in the URL, localStorage or sessionStorage', async () => {
    setGeo(grant());
    installFetch(handler());
    const { user, router } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    await screen.findByRole('list', { name: 'Nearby stops' });
    const row = within(screen.getByRole('list', { name: 'Nearby stops' })).getAllByRole('listitem')[0];
    await user.click(within(row).getByRole('button', { name: 'Use as origin' }));
    const dump = JSON.stringify([router.state.location, { ...localStorage }, { ...sessionStorage }, document.cookie]);
    expect(dump).not.toMatch(/28\.61|77\.21/);
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it('empty result: says so and suggests a larger radius', async () => {
    setGeo(grant());
    installFetch(handler([]));
    const { user } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    expect(await screen.findByText('No stops within 500 m')).toBeInTheDocument();
  });

  it('API error: message and a working retry', async () => {
    setGeo(grant());
    let fail500 = true;
    const f = installFetch((u) => (u.pathname.endsWith('/stops/nearby') ? (fail500 ? { status: 500, body: { error: { code: 'x', message: 'boom' } } } : { status: 200, body: nearbyBody(ITEMS) }) : undefined));
    const { user } = renderApp('/nearby');
    await user.click(await screen.findByRole('button', { name: 'Use my location' }));
    expect(await screen.findByText('Could not find nearby stops')).toBeInTheDocument();
    fail500 = false;
    await user.click(screen.getByRole('button', { name: /try again|retry/i }));
    expect(await screen.findByRole('list', { name: 'Nearby stops' })).toBeInTheDocument();
    expect(nearbyCalls(f).length).toBeGreaterThanOrEqual(2);
  });

  it('is reachable from the home page', async () => {
    installFetch();
    const { user, router } = renderApp('/');
    await user.click(await screen.findByRole('link', { name: /Find stops near you/ }));
    expect(router.state.location.pathname).toBe('/nearby');
  });
});
