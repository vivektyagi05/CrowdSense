import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { installFetch, renderApp } from './test/harness.jsx';
import { savePlace } from './features/places/placesStore.js';

const nearBody = { radius_m: 500, limit: 30, total_in_radius: 1, returned: 1, index: 'rtree', data_basis: 'gtfs_stops', notice: 'n', items: [{ stop_id: 'A', stop_name: 'Alpha', stop_lat: 28.6, stop_lon: 77.2, distance_m: 40, bearing_deg: 0, compass: 'N', routes_count: 1, route_names: ['5'], cluster_id: null }] };
const handler = (u) => (u.pathname.endsWith('/stops/nearby') ? { status: 200, body: nearBody } : undefined);

const PAGES = [
  ['/nearby', 'Stops near you'],
  ['/stops/271', 'GGS University ISBT Kashmere Gate'],
  ['/journeys/72_06_40?from=106&to=216&date=2026-11-11&board=06%3A56%3A26', /Banglow Road/],
  ['/routes/72', '114UP'],
];

describe('phase 4 accessibility', () => {
  it.each(PAGES)('%s: one h1, named controls and regions, unique ids, no dead links, map has a text equivalent', async (path, h1) => {
    installFetch(handler);
    renderApp(path);
    await screen.findByRole('heading', { level: 1, name: h1 });
    await new Promise((r) => setTimeout(r, 500));
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    const unnamed = [...document.querySelectorAll('button, a[href], input, select')].filter((el) => !(el.getAttribute('aria-label') || el.labels?.[0]?.textContent || el.textContent?.trim() || el.getAttribute('title')));
    expect(unnamed.map((e) => e.outerHTML.slice(0, 80))).toEqual([]);
    const ids = [...document.querySelectorAll('[id]')].map((e) => e.id);
    expect(ids.filter((id, i) => ids.indexOf(id) !== i)).toEqual([]);
    expect(document.querySelectorAll('a[href="#"]')).toHaveLength(0);
    const maps = document.querySelectorAll('section.map');
    for (const m of maps) expect(m.getAttribute('aria-label')).toBeTruthy();
    for (const region of screen.queryAllByRole('region')) expect(region).toHaveAccessibleName();
  });

  it('no WebGL (jsdom): the nearby page still gives the full text list and a visible "Map unavailable" card', async () => {
    installFetch(handler);
    const { user } = renderApp('/nearby?from=A');
    await screen.findByRole('heading', { level: 1, name: 'Stops near you' });
    expect(screen.getByRole('region', { name: 'Map of nearby stops' })).toBeInTheDocument();
    expect(screen.getByText('Map unavailable')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Use my location' }));       // no geolocation in jsdom: honest message
    expect(await screen.findByText(/could not determine a location/)).toBeInTheDocument();
  });

  it('the bottom sheet handle is a real, labelled, keyboard-operable button that exposes its state', async () => {
    installFetch(handler);
    const { user } = renderApp('/nearby');
    const handle = await screen.findByRole('button', { name: /Find stops near you/ });
    expect(handle).toHaveAttribute('aria-expanded', 'true');
    expect(handle).toHaveAttribute('aria-controls');
    handle.focus();
    await user.keyboard('{Enter}');   // half -> full
    await user.keyboard('{Enter}');   // full -> collapsed
    expect(handle).toHaveAttribute('aria-expanded', 'false');
    await user.keyboard(' ');         // collapsed -> half
    expect(handle).toHaveAttribute('aria-expanded', 'true');
  });

  it('places panel controls are named and reachable (home with a saved stop)', async () => {
    savePlace('106');
    installFetch(handler);
    renderApp('/');
    const panel = await screen.findByRole('region', { name: 'Your places' });
    await within(panel).findByRole('button', { name: /Use .* as origin/ });
    for (const b of within(panel).getAllByRole('button')) expect(b).toHaveAccessibleName();
  });
});
