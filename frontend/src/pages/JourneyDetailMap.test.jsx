import { screen, waitFor, within } from '@testing-library/react';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { installFetch, renderApp } from '../test/harness.jsx';

// The map boundary is replaced by a probe that exposes exactly what the page hands to the map.
const probe = vi.hoisted(() => ({ props: null }));
vi.mock('../features/map/LazyMapView.jsx', () => ({
  default: (props) => {
    probe.props = props;
    return <div data-testid="map-probe" data-selected={props.selectedStopId ?? ''} data-line={props.data.line ? 'yes' : 'no'} data-status={props.data.status} />;
  },
}));

const URL_ = '/journeys/72_06_40?from=106&to=216&date=2026-11-11&board=06%3A56%3A26';
const LEG = [[77.2, 28.6], [77.21, 28.61], [77.22, 28.62]];
const okShape = { status: 'ok', reason: null, trip_id: '72_06_40', shape_id: 'S', data_basis: 'gtfs_shape', coordinates: LEG, point_count_original: 90, point_count_returned: 3, simplified: true, tolerance_m: 5, length_m: 3300, match_method: 'projection', boarding: { stop_id: '106', distance_to_shape_m: 4 }, alighting: { stop_id: '216', distance_to_shape_m: 6 } };
const legShape = (body, status = 200) => (u) => (u.pathname.endsWith('/shape') ? { status, body } : undefined);

beforeEach(() => { probe.props = null; });

describe('journey details map', () => {
  it('asks the backend for the leg between the journey stops and gives the map exactly that geometry', async () => {
    const f = installFetch(legShape(okShape));
    renderApp(URL_);
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-line', 'yes'));
    const call = f.calls.find((u) => u.pathname.endsWith('/trips/72_06_40/shape'));
    expect(call.searchParams.get('from_stop_id')).toBe('106');
    expect(call.searchParams.get('to_stop_id')).toBe('216');
    expect(call.searchParams.get('board')).toBe('06:56:26');
    expect(call.searchParams.get('fallback')).toBeNull();                          // never the straight-line stop fallback
    expect(probe.props.data.line.geometry.coordinates).toEqual(LEG);
    const roles = probe.props.data.stops.features.map((x) => x.properties.role);
    expect(roles[0]).toBe('board'); expect(roles[roles.length - 1]).toBe('alight');
    expect(await screen.findByText(/Path drawn from the published GTFS shape/)).toBeInTheDocument();
  });

  it('timeline -> map: hovering/focusing a stop highlights it on the map', async () => {
    installFetch(legShape(okShape));
    const { user } = renderApp(URL_);
    const timeline = await screen.findByRole('list', { name: 'Journey timeline' });
    const link = within(timeline).getAllByRole('link').find((a) => a.getAttribute('href') === '/stops/106');
    await user.hover(link);
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-selected', '106'));
    await user.unhover(link);
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-selected', ''));
    await act(async () => link.focus());
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-selected', '106'));
    await act(async () => link.blur());
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-selected', ''));
  });

  it('map -> timeline: selecting a stop on the map highlights its row and offers the stop page', async () => {
    installFetch(legShape(okShape));
    renderApp(URL_);
    await screen.findByTestId('map-probe');
    await act(async () => probe.props.onSelectStop('216'));
    const row = document.querySelector('[data-stop-id="216"]');
    expect(row).toHaveClass('tl-stop--active');
    expect(screen.getByRole('link', { name: 'Open stop page' })).toHaveAttribute('href', '/stops/216');
  });

  it.each([
    ['no_shape', { ...okShape, status: 'no_shape', coordinates: [], reason: 'trip_has_no_shape_id' }, /Route path not published for this trip/],
    ['unreliable_projection', { ...okShape, status: 'unreliable_projection', coordinates: [], reason: 'x' }, /Path could not be matched reliably/],
  ])('%s: no line, honest message, timeline still complete', async (_n, body, msg) => {
    installFetch(legShape(body));
    renderApp(URL_);
    expect(await screen.findByText(msg)).toBeInTheDocument();
    expect(screen.getByTestId('map-probe')).toHaveAttribute('data-line', 'no');
    expect(screen.getByRole('list', { name: 'Journey timeline' })).toBeInTheDocument();
    expect(screen.getAllByText(/Banglow Road/).length).toBeGreaterThan(0);
    expect(probe.props.data.stops.features.length).toBeGreaterThan(1);              // the stops are still on the map
  });

  it('request failure: message + working Retry, timeline unaffected', async () => {
    let fail = true;
    const f = installFetch((u) => (u.pathname.endsWith('/shape') ? (fail ? { status: 500, body: { error: { code: 'x', message: 'boom' } } } : { status: 200, body: okShape }) : undefined));
    const { user } = renderApp(URL_);
    expect(await screen.findByText(/route path could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Journey timeline' })).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByTestId('map-probe')).toHaveAttribute('data-line', 'yes'));
    expect(f.calls.filter((u) => u.pathname.endsWith('/shape')).length).toBeGreaterThanOrEqual(2);
  });

  it('shows a loading note while the path is requested, then no duplicate shape requests', async () => {
    let release;
    const f = installFetch((u) => (u.pathname.endsWith('/shape') ? new Promise((r) => { release = () => r({ status: 200, body: okShape }); }) : undefined));
    renderApp(URL_);
    expect(await screen.findByText('Loading the route path…')).toBeInTheDocument();
    expect(screen.getByTestId('map-probe')).toHaveAttribute('data-line', 'no');
    await act(async () => release());
    await waitFor(() => expect(screen.queryByText('Loading the route path…')).not.toBeInTheDocument());
    expect(f.calls.filter((u) => u.pathname.endsWith('/shape'))).toHaveLength(1);
  });
});
