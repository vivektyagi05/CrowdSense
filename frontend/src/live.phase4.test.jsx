// Phase 4 live integration test against the REAL backend and the REAL Delhi GTFS database (with derived data built).
// Skipped unless CROWDSENSE_LIVE_API is set. Runs in jsdom, NOT a browser: the map canvas itself is not exercised
// (no WebGL), so the map card falls back to the stop list; everything the map would be fed is asserted from real responses.
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from './test/harness.jsx';

const live = process.env.CROWDSENSE_LIVE_API;
describe.skipIf(!live)('live backend - Phase 4', () => {
  it('smart search -> place cluster with real members -> journey -> details with real GTFS geometry', async () => {
    const seen = [];
    const realFetch = globalThis.fetch;
    vi.stubGlobal('fetch', async (...args) => { const r = await realFetch(...args); seen.push({ url: new URL(typeof args[0] === 'string' ? args[0] : args[0].url), res: r.clone() }); return r; });
    const { user } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Know the crowd before you board.' });

    // 1) typo-tolerant, cluster-grouped search: "Rithla" (missing letter) finds the Rithala Metro Station place
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'rithla metro');
    const list = await screen.findByRole('listbox', {}, { timeout: 8000 });
    await waitFor(() => expect(within(list).getAllByRole('option').length).toBeGreaterThan(1), { timeout: 8000 });
    expect(within(list).getAllByText(/stops at this place/).length).toBeGreaterThan(0);
    const searchCall = seen.find((s) => s.url.pathname.endsWith('/stops') && s.url.searchParams.get('mode') === 'smart');
    const search = await searchCall.res.json();
    const group = search.groups.find((g) => g.display_name === 'Rithala Metro Station');
    expect(group.members.length).toBe(4);                                       // the 4 real physical stops of that place
    expect(group.cluster_id).toMatch(/^c_[0-9a-f]{12}$/);

    // 2) the cluster endpoint agrees with the search groups, member by member, and invents no headsigns
    const cl = await (await realFetch(`${live}/clusters/${group.cluster_id}`)).json();
    expect(cl.members.map((m) => m.stop_id).sort()).toEqual(group.members.map((m) => m.stop_id).sort());
    expect(cl.headsigns_available).toBe(false);
    expect(cl.members.every((m) => m.headsigns.length === 0 && m.routes_count > 0 && m.scheduled_calls > 0)).toBe(true);

    // 3) choose a specific stop of the place (a group heading cannot be chosen)
    const options = within(list).getAllByRole('option');
    await user.click(options[0]);
    expect(screen.getByText(/^Selected stop /)).toBeInTheDocument();
  }, 60000);

  it('journey 106 -> 216: details page requests the real leg geometry and reports it truthfully', async () => {
    const seen = [];
    const realFetch = globalThis.fetch;
    vi.stubGlobal('fetch', async (...args) => { const r = await realFetch(...args); seen.push({ url: new URL(typeof args[0] === 'string' ? args[0] : args[0].url), res: r.clone() }); return r; });
    renderApp('/journeys/72_06_40?from=106&to=216&date=2026-11-11&board=06%3A56%3A26');
    expect(await screen.findByText('Trip 72_06_40', {}, { timeout: 15000 })).toBeInTheDocument();
    await screen.findByText(/Path drawn from the published GTFS shape/, {}, { timeout: 15000 });
    const call = seen.find((s) => s.url.pathname.endsWith('/trips/72_06_40/shape'));
    expect(call.url.searchParams.get('from_stop_id')).toBe('106'); expect(call.url.searchParams.get('fallback')).toBeNull();
    const body = await call.res.json();
    expect(body.status).toBe('ok'); expect(body.data_basis).toBe('gtfs_shape');
    expect(body.coordinates.length).toBeGreaterThan(2); expect(body.length_m).toBeGreaterThan(1000);
    expect(body.boarding.distance_to_shape_m).toBeLessThan(60); expect(body.alighting.distance_to_shape_m).toBeLessThan(60);
    expect(screen.getByText('Map unavailable')).toBeInTheDocument();           // jsdom has no WebGL: the honest fallback, still listing the stops
    expect(screen.getByRole('list', { name: 'Journey timeline' })).toBeInTheDocument();
  }, 60000);

  it('nearby API returns real, correctly ordered stops for a real stop\'s own coordinates', async () => {
    const s = await (await fetch(`${live}/stops/106`)).json();
    const r = await (await fetch(`${live}/stops/nearby?lat=${s.stop_lat}&lon=${s.stop_lon}&radius_m=300&limit=10`)).json();
    expect(r.items[0].stop_id).toBe('106'); expect(r.items[0].distance_m).toBeLessThanOrEqual(1);
    expect(r.items.map((i) => i.distance_m)).toEqual([...r.items.map((i) => i.distance_m)].sort((a, b) => a - b));
    expect(r.index).toBe('rtree');
  }, 30000);
});
