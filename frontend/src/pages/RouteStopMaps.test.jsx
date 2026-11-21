import { screen, waitFor, within } from '@testing-library/react';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import stop106 from '../test/fixtures/stop-106.json';
import stoptimes72 from '../test/fixtures/stoptimes-72.json';
import { installFetch, renderApp } from '../test/harness.jsx';

const probe = vi.hoisted(() => ({ props: null }));
vi.mock('../features/map/LazyMapView.jsx', () => ({
  default: (props) => {
    probe.props = props;
    return <div data-testid="map-probe" data-line={props.data.line ? 'yes' : 'no'} data-stops={props.data.stops.features.length} data-selected={props.selectedStopId ?? ''} />;
  },
}));
beforeEach(() => { probe.props = null; });

const LINE = [[77.2, 28.6], [77.25, 28.65], [77.3, 28.7]];
const shapeItem = (over = {}) => ({ shape_id: 'SH72', trip_count: 5, point_count: 400, geometry_status: 'ok', coordinates: LINE, point_count_original: 400, point_count_returned: 3, simplified: true, tolerance_m: 5, data_basis: 'gtfs_shape', ...over });
const routeShapes = (items) => (u) => (/\/routes\/72\/shapes$/.test(u.pathname) ? { status: 200, body: { route_id: '72', items } } : undefined);

describe('route page map', () => {
  it('draws the published shape with the selected trip\'s ordered stops, loaded AFTER the text list', async () => {
    const f = installFetch(routeShapes([shapeItem()]));
    renderApp('/routes/72');
    await screen.findByText(/Stops of trip/i);
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-line', 'yes'));
    expect(probe.props.data.line.geometry.coordinates).toEqual(LINE);
    expect(probe.props.data.stops.features).toHaveLength(stoptimes72.items.filter((s) => Number.isFinite(s.stop_lat)).length);
    const shapeCall = f.calls.find((u) => u.pathname.endsWith('/routes/72/shapes'));
    expect(shapeCall.searchParams.get('geometry')).toBe('true');
    expect(await screen.findByText(/Path drawn from the published GTFS shape SH72 \(3 of 400 points/)).toBeInTheDocument();
    const order = f.calls.map((u) => u.pathname);
    expect(order.findIndex((p) => p.endsWith('/stop-times'))).toBeLessThan(order.findIndex((p) => p.endsWith('/shapes')));
  });

  it('click a stop on the map: callout with a link to the stop page', async () => {
    installFetch(routeShapes([shapeItem()]));
    renderApp('/routes/72');
    await screen.findByTestId('map-probe');
    const first = stoptimes72.items[0];
    await act(async () => probe.props.onSelectStop(first.stop_id));
    const link = await screen.findByRole('link', { name: 'Open stop page' });
    expect(link).toHaveAttribute('href', `/stops/${first.stop_id}`);
  });

  it('no shape published: no line, honest message, stops still mapped and listed', async () => {
    installFetch(routeShapes([shapeItem({ geometry_status: 'no_shape', coordinates: [], point_count_returned: 0 })]));
    renderApp('/routes/72');
    expect(await screen.findByText(/Route path not published for this trip/)).toBeInTheDocument();
    expect(screen.getByTestId('map-probe')).toHaveAttribute('data-line', 'no');
    expect(Number(screen.getByTestId('map-probe').dataset.stops)).toBeGreaterThan(1);
  });

  it('several shapes: a selector that really switches the drawn geometry', async () => {
    const other = [[77.0, 28.5], [77.1, 28.55]];
    installFetch(routeShapes([shapeItem(), shapeItem({ shape_id: 'SH99', coordinates: other, point_count_returned: 2 })]));
    const { user } = renderApp('/routes/72');
    const group = await screen.findByRole('group', { name: 'Route shapes' });
    expect(within(group).getByRole('button', { name: /SH72/ })).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(group).getByRole('button', { name: /SH99/ }));
    await waitFor(() => expect(probe.props.data.line.geometry.coordinates).toEqual(other));
    expect(within(group).getByRole('button', { name: /SH99/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shape request fails: error with retry; the stop list is unaffected', async () => {
    let fail = true;
    installFetch((u) => (/\/routes\/72\/shapes$/.test(u.pathname) ? (fail ? { status: 500, body: { error: { code: 'x', message: 'boom' } } } : { status: 200, body: { route_id: '72', items: [shapeItem()] } }) : undefined));
    const { user } = renderApp('/routes/72');
    expect(await screen.findByText('Could not load the route path')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /^Stops of trip/ })).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: /try again|retry/i }));
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-line', 'yes'));
  });

  it('no stale "maps arrive in a later phase" text remains', async () => {
    installFetch(routeShapes([shapeItem()]));
    renderApp('/routes/72');
    await screen.findByText(/shape.*published/);
    expect(screen.queryByText(/later phase/i)).not.toBeInTheDocument();
  });
});

const cluster = { cluster_id: 'c_106', display_name: 'Stop 106 place', centroid_lat: 28.6, centroid_lon: 77.2, stop_count: 2, rule: 'x', threshold_m: 150, headsigns_available: false, notice: 'n',
  members: [{ stop_id: '106', stop_name: stop106.stop_name, stop_lat: 28.6001, stop_lon: 77.2, distance_from_centroid_m: 11, bearing_from_centroid_deg: 0, compass: 'N', routes_count: 1, route_names: ['1'], scheduled_calls: 4, headsigns: [] },
    { stop_id: '999', stop_name: stop106.stop_name, stop_lat: 28.5999, stop_lon: 77.2, distance_from_centroid_m: 11, bearing_from_centroid_deg: 180, compass: 'S', routes_count: 2, route_names: ['7UP', '8'], scheduled_calls: 9, headsigns: [] }] };
const near = (items) => ({ radius_m: 400, limit: 20, total_in_radius: items.length, returned: items.length, index: 'rtree', data_basis: 'gtfs_stops', notice: 'n', items });
const nearItem = (id, name, d) => ({ stop_id: id, stop_name: name, stop_lat: 28.601, stop_lon: 77.2, distance_m: d, bearing_deg: 90, compass: 'E', routes_count: 1, route_names: ['5'], cluster_id: null });
const stopPage = (extra = {}, nearbyItems = [nearItem('300', 'Gamma Stop', 120)]) => (u) => {
  if (u.pathname.endsWith('/stops/106')) return { status: 200, body: { ...stop106, cluster_id: 'c_106', ...extra } };
  if (u.pathname.endsWith('/clusters/c_106')) return { status: 200, body: cluster };
  if (u.pathname.endsWith('/stops/nearby')) return { status: 200, body: near(nearbyItems) };
  return undefined;
};

describe('stop page map', () => {
  it('maps this stop, its cluster siblings and nearby stops (real data), with roles', async () => {
    const f = installFetch(stopPage());
    renderApp('/stops/106');
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-stops', '3'));
    const roles = Object.fromEntries(probe.props.data.stops.features.map((x) => [x.properties.stopId, x.properties.role]));
    expect(roles).toEqual({ 106: 'current', 999: 'sibling', 300: 'stop' });
    expect(probe.props.data.line).toBeNull();                                          // a stop page never draws a path
    const call = f.calls.find((u) => u.pathname.endsWith('/stops/nearby'));
    expect(Number(call.searchParams.get('lat'))).toBeCloseTo(stop106.stop_lat, 6);     // the STOP's own coordinates, not the visitor's
    expect(call.searchParams.get('radius_m')).toBe('400');
  });

  it('lists siblings and nearby stops as text with distance/routes, linking to their stop pages', async () => {
    installFetch(stopPage());
    renderApp('/stops/106');
    const sib = await screen.findByRole('list', { name: 'Other stops at this place' });
    expect(within(sib).getByRole('link')).toHaveAttribute('href', '/stops/999');
    expect(sib).toHaveTextContent('11 m south of the centre'); expect(sib).toHaveTextContent('routes 7UP, 8');
    const nb = await screen.findByRole('list', { name: 'Nearby stops' });
    expect(within(nb).getByRole('link', { name: 'Gamma Stop' })).toHaveAttribute('href', '/stops/300');
    expect(nb).toHaveTextContent('120 m east');
    expect(screen.getByText(/not walking distances/)).toBeInTheDocument();
  });

  it('hover/focus on a list row highlights it on the map; map click offers the stop page', async () => {
    installFetch(stopPage());
    const { user } = renderApp('/stops/106');
    const link = await within(await screen.findByRole('list', { name: 'Nearby stops' })).findByRole('link', { name: 'Gamma Stop' });
    await user.hover(link);
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-selected', '300'));
    await user.unhover(link);
    await act(async () => probe.props.onSelectStop('999'));
    expect(await screen.findByRole('link', { name: 'Open stop page' })).toHaveAttribute('href', '/stops/999');
  });

  it('no cluster id (derived data not built): still maps nearby stops, no cluster section', async () => {
    installFetch((u) => (u.pathname.endsWith('/stops/106') ? { status: 200, body: stop106 } : stopPage()(u)));
    renderApp('/stops/106');
    await screen.findByRole('list', { name: 'Nearby stops' });
    expect(screen.queryByText('Same place, other stops')).not.toBeInTheDocument();
  });

  it('nearby failure: error + retry, cluster section unaffected; empty result: says so', async () => {
    let fail = true;
    installFetch((u) => (u.pathname.endsWith('/stops/nearby') ? (fail ? { status: 500, body: { error: { code: 'x', message: 'boom' } } } : { status: 200, body: near([]) }) : stopPage()(u)));
    const { user } = renderApp('/stops/106');
    expect(await screen.findByText('Could not load nearby stops')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Other stops at this place' })).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: /try again|retry/i }));
    expect(await screen.findByText('No other stops within 400 m')).toBeInTheDocument();
  });
});
