import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { installFetch, renderApp } from '../../test/harness.jsx';
import * as store from './placesStore.js';

const stored = () => JSON.parse(localStorage.getItem(store.STORAGE_KEY));

describe('placesStore', () => {
  beforeEach(() => store.resetPlacesCache());

  it('uses the versioned key and stores stop IDs only (no names, coordinates or positions)', () => {
    store.addRecent('106'); store.savePlace('216');
    expect(store.STORAGE_KEY).toBe('crowdsense.places.v1');
    const s = stored();
    expect(s.version).toBe(1);
    expect(s.saved.map((x) => Object.keys(x).sort())).toEqual([['at', 'id']]);
    expect(s.recent.map((x) => x.id)).toEqual(['106']);
    expect(localStorage.getItem(store.STORAGE_KEY)).not.toMatch(/lat|lon|name|\d+\.\d{4}/i);
  });

  it('de-dupes recents (most recent first) and caps them at 20', () => {
    for (let i = 0; i < 25; i += 1) store.addRecent(`s${i}`);
    store.addRecent('s10');
    const ids = stored().recent.map((r) => r.id);
    expect(ids).toHaveLength(store.MAX_RECENT);
    expect(ids[0]).toBe('s10'); expect(new Set(ids).size).toBe(ids.length);
    expect(ids).not.toContain('s0');
  });

  it('caps saved at 10, refuses the 11th honestly, and saving twice is a no-op', () => {
    for (let i = 0; i < 10; i += 1) expect(store.savePlace(`s${i}`)).toEqual({ ok: true });
    expect(store.savePlace('s3')).toEqual({ ok: true });
    expect(store.savePlace('extra')).toEqual({ ok: false, reason: 'full' });
    expect(stored().saved).toHaveLength(10);
    expect(store.savePlace('')).toEqual({ ok: false, reason: 'invalid' });
    expect(store.savePlace('x'.repeat(300))).toEqual({ ok: false, reason: 'invalid' });
  });

  it('remove and clear-all delete data', () => {
    store.savePlace('a'); store.addRecent('b'); store.addRecent('a');
    store.removePlace('a');
    expect(stored().saved).toEqual([]); expect(stored().recent.map((r) => r.id)).toEqual(['b']);
    store.clearAllPlaces();
    expect(stored()).toEqual({ version: 1, saved: [], recent: [] });
  });

  it.each([['not json', '{{{'], ['wrong version', JSON.stringify({ version: 2, saved: [], recent: [] })], ['array', '[1,2]'], ['null', 'null']])('corrupted storage (%s) is ignored, flagged, and overwritten by the next write', (_n, text) => {
    localStorage.setItem(store.STORAGE_KEY, text);
    store.resetPlacesCache();
    const snap = store.getSnapshot();
    expect(snap.corrupted).toBe(true); expect(snap.state).toEqual({ version: 1, saved: [], recent: [] });
    store.savePlace('ok');
    expect(stored().saved.map((s) => s.id)).toEqual(['ok']);
  });

  it('malformed entries inside a valid document are dropped, the rest kept', () => {
    localStorage.setItem(store.STORAGE_KEY, JSON.stringify({ version: 1, saved: [{ id: 'a' }, { id: 5 }, null, { id: 'a' }, 'b', { id: '' }], recent: 'nope' }));
    store.resetPlacesCache();
    expect(store.getSnapshot().state.saved.map((s) => s.id)).toEqual(['a', 'b']);
    expect(store.getSnapshot().state.recent).toEqual([]);
  });

  it('a blocked/throwing localStorage never throws: reads are empty, writes report failure', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('quota', 'QuotaExceededError'); });
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
    store.resetPlacesCache();
    expect(() => store.getSnapshot()).not.toThrow();
    expect(store.getSnapshot().state.saved).toEqual([]);
    expect(store.savePlace('x')).toEqual({ ok: false, reason: 'storage' });
    expect(() => store.addRecent('y')).not.toThrow();
    spy.mockRestore(); get.mockRestore();
  });
});

const stop = (id, name) => ({ stop_id: id, stop_name: name, stop_lat: 28.6, stop_lon: 77.2, routes: [], stop_time_count: 3 });
const handler = (known) => (u) => {
  const m = /\/stops\/([^/]+)$/.exec(u.pathname);
  if (m && known[m[1]]) return { status: 200, body: stop(m[1], known[m[1]]) };
  if (m && /^\d+$/.test(m[1]) || (m && m[1] === 'gone')) return { status: 404, body: { error: { code: 'not_found', message: `Unknown stop ${m[1]}.` } } };
  return undefined;
};

describe('places panel', () => {
  beforeEach(() => store.resetPlacesCache());

  it('is absent when there is nothing to show, and says "stored on this device only" when there is', async () => {
    installFetch(handler({ 106: 'Alpha' }));
    const { unmount } = renderApp('/');
    await screen.findByRole('form', { name: 'Journey search' });
    expect(screen.queryByText('Your places')).not.toBeInTheDocument();
    unmount();
    store.savePlace('106');
    renderApp('/');
    expect(await screen.findByText('Your places')).toBeInTheDocument();
    expect(screen.getByText(/Stored on this device only/)).toBeInTheDocument();
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
  });

  it('using a saved place fills the journey form with that real stop', async () => {
    installFetch(handler({ 106: 'Alpha', 216: 'Beta' }));
    store.savePlace('106'); store.savePlace('216');
    const { user } = renderApp('/');
    await screen.findByText('Alpha');
    await user.click(await screen.findByRole('button', { name: 'Use Alpha as origin' }));
    await user.click(screen.getByRole('button', { name: 'Use Beta as destination' }));
    expect(screen.getByRole('combobox', { name: 'From' })).toHaveValue('Alpha');
    expect(screen.getByRole('combobox', { name: 'To' })).toHaveValue('Beta');
    expect(screen.getByText('Selected stop 106')).toBeInTheDocument();
  });

  it('a stale (deleted) stop id is reported honestly and can be removed', async () => {
    installFetch(handler({ 106: 'Alpha' }));
    store.savePlace('gone'); store.savePlace('106');
    const { user } = renderApp('/');
    expect(await screen.findByText('Stop gone is no longer in the timetable.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove stop gone from your places' }));
    expect(screen.queryByText(/Stop gone/)).not.toBeInTheDocument();
    expect(stored().saved.map((s) => s.id)).toEqual(['106']);
  });

  it('clear-all empties saved and recent places and hides the panel', async () => {
    installFetch(handler({ 106: 'Alpha', 216: 'Beta' }));
    store.savePlace('106'); store.addRecent('216');
    const { user } = renderApp('/');
    await screen.findByText('Beta');
    await user.click(screen.getByRole('button', { name: 'Clear all saved and recent places' }));
    expect(screen.queryByText('Your places')).not.toBeInTheDocument();
    expect(stored()).toEqual({ version: 1, saved: [], recent: [] });
  });

  it('corrupted storage: a notice, no crash, the form still works', async () => {
    localStorage.setItem(store.STORAGE_KEY, '{{{ nope');
    installFetch(handler({}));
    renderApp('/');
    expect(await screen.findByText(/could not be read, so they were ignored/)).toBeInTheDocument();
    expect(screen.getByRole('form', { name: 'Journey search' })).toBeInTheDocument();
  });

  it('a submitted search records both stops as recent (ids only)', async () => {
    installFetch(handler({ 106: 'Alpha', 216: 'Beta' }));
    store.savePlace('106');
    const { user } = renderApp('/');
    await screen.findByText('Alpha');
    await user.click(screen.getByRole('button', { name: 'Use Alpha as origin' }));
    store.savePlace('216');
    await user.click(await screen.findByRole('button', { name: 'Use Beta as destination' }));
    await user.click(screen.getByRole('button', { name: 'Search journeys' }));
    await waitFor(() => expect(stored().recent.map((r) => r.id).sort()).toEqual(['106', '216']));
  });
});

describe('save toggle on the stop page', () => {
  beforeEach(() => store.resetPlacesCache());

  it('saves and unsaves, with a pressed state and persistence', async () => {
    installFetch();
    const { user } = renderApp('/stops/106');
    const btn = await screen.findByRole('button', { name: 'Save this place' });
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    await user.click(btn);
    expect(await screen.findByRole('button', { name: 'Saved on this device' })).toHaveAttribute('aria-pressed', 'true');
    expect(stored().saved.map((s) => s.id)).toEqual(['106']);
    await user.click(screen.getByRole('button', { name: 'Saved on this device' }));
    expect(stored().saved).toEqual([]);
  });

  it('says so when the list is full', async () => {
    for (let i = 0; i < 10; i += 1) store.savePlace(`s${i}`);
    installFetch();
    const { user } = renderApp('/stops/106');
    await user.click(await screen.findByRole('button', { name: 'Save this place' }));
    expect(await screen.findByText(/save up to 10 places/)).toBeInTheDocument();
  });
});
