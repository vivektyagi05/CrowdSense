import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { legMapData } from '../../lib/geo.js';
import MapView from './MapView.jsx';

const line = [[77.2, 28.6], [77.21, 28.61]];
const stops = [{ id: 'A', name: 'Alpha', lat: 28.6, lon: 77.2, sequence: 1 }, { id: 'B', name: 'Beta', lat: 28.61, lon: 77.21, sequence: 2 }];
const data = legMapData({ shape: { status: 'ok', coordinates: line }, stops, boardId: 'A', alightId: 'B' });
const fallbackStops = stops.map((s) => ({ id: s.id, name: s.name, href: `/stops/${s.id}` }));

/** A fake engine at the adapter boundary: records exactly what the app hands to the map. */
function fakeEngine() {
  const calls = { created: [], setData: [], fit: [], zoom: [], selected: [], destroyed: 0 };
  let opts;
  const adapter = {
    setData: (d) => calls.setData.push(d), fitBounds: (b) => calls.fit.push(b), zoomBy: (d) => calls.zoom.push(d),
    setSelected: (id) => calls.selected.push(id), destroy: () => { calls.destroyed += 1; },
  };
  const engine = { createMapAdapter: (o) => { opts = o; calls.created.push(o); return adapter; } };
  return { calls, loadEngine: () => Promise.resolve(engine), opts: () => opts };
}

const renderMap = (props = {}) => render(<MemoryRouter><MapView label="Journey map" data={data} fallbackStops={fallbackStops} checkWebGL={() => true} styleUrl="https://tiles.example/style.json" {...props} /></MemoryRouter>);

describe('MapView', () => {
  it('hands the map exactly the API geometry and frames the bounds', async () => {
    const f = fakeEngine();
    renderMap({ loadEngine: f.loadEngine });
    await waitFor(() => expect(f.calls.setData).toHaveLength(1));
    expect(f.calls.setData[0].line.geometry.coordinates).toEqual(line);          // byte-for-byte what the API returned
    expect(f.calls.setData[0].stops.features.map((x) => x.properties.stopId)).toEqual(['A', 'B']);
    expect(f.calls.fit[0]).toEqual([[77.2, 28.6], [77.21, 28.61]]);
    expect(f.calls.created[0].styleUrl).toBe('https://tiles.example/style.json');
  });

  it('does NOT re-create the map when data changes; it only updates the sources', async () => {
    const f = fakeEngine();
    const { rerender } = renderMap({ loadEngine: f.loadEngine });
    await waitFor(() => expect(f.calls.created).toHaveLength(1));
    const next = legMapData({ shape: { status: 'ok', coordinates: [[77.3, 28.7], [77.31, 28.71]] }, stops, boardId: 'A', alightId: 'B' });
    rerender(<MemoryRouter><MapView label="Journey map" data={next} fallbackStops={fallbackStops} checkWebGL={() => true} loadEngine={f.loadEngine} styleUrl="" /></MemoryRouter>);
    await waitFor(() => expect(f.calls.setData).toHaveLength(2));
    expect(f.calls.created).toHaveLength(1);
    expect(f.calls.fit).toHaveLength(2);                                          // new bounds -> re-framed
  });

  it('does not re-frame when only the selection changes', async () => {
    const f = fakeEngine();
    const { rerender } = renderMap({ loadEngine: f.loadEngine });
    await waitFor(() => expect(f.calls.fit).toHaveLength(1));
    rerender(<MemoryRouter><MapView label="Journey map" data={data} fallbackStops={fallbackStops} checkWebGL={() => true} loadEngine={f.loadEngine} styleUrl="" selectedStopId="B" /></MemoryRouter>);
    await waitFor(() => expect(f.calls.selected).toContain('B'));
    expect(f.calls.fit).toHaveLength(1);
    expect(f.calls.created).toHaveLength(1);
  });

  it('destroys the map on unmount (no leaked listeners)', async () => {
    const f = fakeEngine();
    const { unmount } = renderMap({ loadEngine: f.loadEngine });
    await waitFor(() => expect(f.calls.created).toHaveLength(1));
    unmount();
    expect(f.calls.destroyed).toBe(1);
  });

  it('StrictMode double mount leaves exactly one live map', async () => {
    const { StrictMode } = await import('react');
    const f = fakeEngine();
    render(<StrictMode><MemoryRouter><MapView label="m" data={data} checkWebGL={() => true} loadEngine={f.loadEngine} styleUrl="" /></MemoryRouter></StrictMode>);
    await waitFor(() => expect(f.calls.created.length).toBeGreaterThanOrEqual(1));
    expect(f.calls.created.length - f.calls.destroyed).toBe(1);
  });

  it('routes engine callbacks to the page (select / hover)', async () => {
    const f = fakeEngine();
    const onSelectStop = vi.fn(); const onHoverStop = vi.fn();
    renderMap({ loadEngine: f.loadEngine, onSelectStop, onHoverStop });
    await waitFor(() => expect(f.calls.created).toHaveLength(1));
    f.opts().onStopClick('B'); f.opts().onStopHover('A'); f.opts().onStopHover(null);
    expect(onSelectStop).toHaveBeenCalledWith('B');
    expect(onHoverStop.mock.calls.map((c) => c[0])).toEqual(['A', null]);
  });

  it('controls are real buttons wired to the adapter and enabled only once the map is ready', async () => {
    const f = fakeEngine(); const user = userEvent.setup();
    renderMap({ loadEngine: f.loadEngine });
    await waitFor(() => expect(f.calls.created).toHaveLength(1));
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeDisabled();
    act(() => f.opts().onReady());
    await user.click(screen.getByRole('button', { name: 'Zoom in' }));
    await user.click(screen.getByRole('button', { name: 'Zoom out' }));
    await user.click(screen.getByRole('button', { name: 'Reset view' }));
    expect(f.calls.zoom).toEqual([1, -1]);
    expect(f.calls.fit).toHaveLength(2);                                          // initial frame + reset
    expect(screen.getByRole('group', { name: 'Map controls' })).toBeInTheDocument();
  });

  it('reached by keyboard: Tab lands on the controls, Enter activates', async () => {
    const f = fakeEngine(); const user = userEvent.setup();
    renderMap({ loadEngine: f.loadEngine });
    await waitFor(() => expect(f.calls.created).toHaveLength(1));
    act(() => f.opts().onReady());
    await user.tab();
    expect(screen.getByRole('button', { name: 'Zoom in' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(f.calls.zoom).toEqual([1]);
  });

  describe('degradation matrix', () => {
    it('WebGL unavailable: never downloads the engine, shows the card WITH the stops', () => {
      const loadEngine = vi.fn();
      renderMap({ checkWebGL: () => false, loadEngine });
      expect(loadEngine).not.toHaveBeenCalled();
      expect(screen.getByText('Map unavailable')).toBeInTheDocument();
      expect(screen.getByText(/needs WebGL/)).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Alpha' })).toHaveAttribute('href', '/stops/A');
      expect(screen.getByRole('link', { name: 'Beta' })).toBeInTheDocument();
    });

    it('engine chunk fails to load: card with stops', async () => {
      renderMap({ loadEngine: () => Promise.reject(new Error('chunk 404')) });
      expect(await screen.findByText('Map unavailable')).toBeInTheDocument();
      expect(screen.getByText(/could not be loaded/)).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Alpha' })).toBeInTheDocument();
    });

    it('fatal init error: card with stops', async () => {
      const f = fakeEngine();
      renderMap({ loadEngine: f.loadEngine });
      await waitFor(() => expect(f.calls.created).toHaveLength(1));
      act(() => f.opts().onFatalError(new Error('boom')));
      expect(await screen.findByText('Map unavailable')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Beta' })).toBeInTheDocument();
    });

    it('no style URL: still draws route+stops (blank basemap) and says so', async () => {
      const f = fakeEngine();
      renderMap({ loadEngine: f.loadEngine, styleUrl: '' });
      await waitFor(() => expect(f.calls.created).toHaveLength(1));
      expect(f.calls.created[0].styleUrl).toBe('');
      expect(screen.getByText(/No street basemap is configured/)).toBeInTheDocument();
      expect(f.calls.setData[0].line).not.toBeNull();
    });

    it('tile/style failure: warns, keeps the route and stops', async () => {
      const f = fakeEngine();
      renderMap({ loadEngine: f.loadEngine });
      await waitFor(() => expect(f.calls.created).toHaveLength(1));
      act(() => f.opts().onBasemapError('tile 500'));
      expect(await screen.findByText(/Street tiles could not be loaded/)).toBeInTheDocument();
      expect(screen.queryByText('Map unavailable')).not.toBeInTheDocument();
      expect(screen.queryByText(/No street basemap is configured/)).not.toBeInTheDocument();
    });

    it('slow network: tells the user, offers the text list, recovers when ready', async () => {
      vi.useFakeTimers();
      try {
        const f = fakeEngine();
        renderMap({ loadEngine: f.loadEngine });
        await act(async () => { await Promise.resolve(); });
        expect(screen.getByText('Loading map…')).toBeInTheDocument();
        await act(async () => { vi.advanceTimersByTime(6100); });
        expect(screen.getByText(/taking longer than usual/)).toBeInTheDocument();
        act(() => f.opts().onReady());
        expect(screen.queryByText(/taking longer than usual/)).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Zoom in' })).toBeEnabled();
      } finally { vi.useRealTimers(); }
    });

    it('geometry missing: the map still gets the stops and NO line', async () => {
      const f = fakeEngine();
      const noShape = legMapData({ shape: { status: 'no_shape', coordinates: [] }, stops, boardId: 'A', alightId: 'B' });
      renderMap({ loadEngine: f.loadEngine, data: noShape });
      await waitFor(() => expect(f.calls.setData).toHaveLength(1));
      expect(f.calls.setData[0].line).toBeNull();
      expect(f.calls.setData[0].stops.features).toHaveLength(2);
    });
  });

  it('the section has an accessible name', () => {
    renderMap({ checkWebGL: () => false });
    expect(screen.getByRole('region', { name: 'Journey map' })).toBeInTheDocument();
  });
});
