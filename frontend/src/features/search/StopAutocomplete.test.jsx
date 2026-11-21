import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { installFetch } from '../../test/harness.jsx';
import roop from '../../test/fixtures/stops-search-roop.json';
import StopAutocomplete from './StopAutocomplete.jsx';

function Harness({ onChange }) {
  const [stop, setStop] = useState(null);
  return <StopAutocomplete label="From" value={stop} onSelect={(s) => { setStop(s); onChange?.(s); }} />;
}
const stopCalls = (f) => f.calls.filter((u) => u.pathname.endsWith('/stops'));
const resultsFor = (term) => (term.startsWith('roop') ? { status: 200, body: roop } : { status: 200, body: { items: [], total: 0, limit: 8, offset: 0 } });

describe('StopAutocomplete', () => {
  it('does not search below the minimum length, then searches once after the debounce (not per keystroke)', async () => {
    const f = installFetch((u) => (u.pathname.endsWith('/stops') ? resultsFor(u.searchParams.get('q')) : undefined));
    const user = userEvent.setup();
    render(<Harness />);
    const box = screen.getByRole('combobox', { name: 'From' });
    await user.type(box, 'r');
    expect(await screen.findByText(/at least 2 letters/i)).toBeInTheDocument();
    await user.type(box, 'oop');
    await screen.findAllByRole('option');
    expect(stopCalls(f)).toHaveLength(1);
    expect(stopCalls(f)[0].searchParams.get('q')).toBe('roop');
  });

  it('exposes listbox semantics and selects with the keyboard (ArrowDown, ArrowDown, Enter)', async () => {
    installFetch((u) => (u.pathname.endsWith('/stops') ? resultsFor(u.searchParams.get('q')) : undefined));
    const user = userEvent.setup();
    const seen = [];
    render(<Harness onChange={(s) => seen.push(s)} />);
    const box = screen.getByRole('combobox', { name: 'From' });
    await user.type(box, 'roop');
    const options = await screen.findAllByRole('option');
    expect(box).toHaveAttribute('aria-expanded', 'true');
    expect(box).toHaveAttribute('aria-controls', screen.getByRole('listbox').id);
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(box).toHaveAttribute('aria-activedescendant', options[1].id);
    expect(options[1]).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{Enter}');
    expect(seen.at(-1).stop_id).toBe(roop.items[1].stop_id);
    expect(box).toHaveValue(roop.items[1].stop_name);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(screen.getByText(`Selected stop ${roop.items[1].stop_id}`)).toBeInTheDocument();
  });

  it('wraps ArrowUp to the last option and closes on Escape without selecting', async () => {
    installFetch((u) => (u.pathname.endsWith('/stops') ? resultsFor(u.searchParams.get('q')) : undefined));
    const user = userEvent.setup();
    const seen = [];
    render(<Harness onChange={(s) => seen.push(s)} />);
    const box = screen.getByRole('combobox');
    await user.type(box, 'roop');
    const options = await screen.findAllByRole('option');
    await user.keyboard('{ArrowUp}');
    expect(box).toHaveAttribute('aria-activedescendant', options.at(-1).id);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(seen).toHaveLength(0);
    expect(box).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows distinguishing metadata (stop id and coordinates) because many stops share a name', async () => {
    installFetch((u) => (u.pathname.endsWith('/stops') ? resultsFor(u.searchParams.get('q')) : undefined));
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('combobox'), 'roop');
    const options = await screen.findAllByRole('option');
    expect(options[0]).toHaveTextContent(`Stop ${roop.items[0].stop_id}`);
    expect(options[0]).toHaveTextContent('28.6848');
  });

  it('discards the selection when the text is edited: free text is never a valid stop', async () => {
    installFetch((u) => (u.pathname.endsWith('/stops') ? resultsFor(u.searchParams.get('q')) : undefined));
    const user = userEvent.setup();
    const seen = [];
    render(<Harness onChange={(s) => seen.push(s)} />);
    const box = screen.getByRole('combobox');
    await user.type(box, 'roop');
    await user.click((await screen.findAllByRole('option'))[0]);
    expect(seen.at(-1)).not.toBeNull();
    await user.type(box, 'x');
    expect(seen.at(-1)).toBeNull();
    expect(screen.queryByText(/Selected stop/)).not.toBeInTheDocument();
    expect(screen.getByText(/Pick a stop from the list/)).toBeInTheDocument();
  });

  it('clears text and selection with the clear button and returns focus to the input', async () => {
    installFetch((u) => (u.pathname.endsWith('/stops') ? resultsFor(u.searchParams.get('q')) : undefined));
    const user = userEvent.setup();
    const seen = [];
    render(<Harness onChange={(s) => seen.push(s)} />);
    const box = screen.getByRole('combobox');
    await user.type(box, 'roop');
    await user.click((await screen.findAllByRole('option'))[0]);
    await user.click(screen.getByRole('button', { name: 'Clear from' }));
    expect(box).toHaveValue('');
    expect(seen.at(-1)).toBeNull();
    expect(box).toHaveFocus();
  });

  it('says so when nothing matches', async () => {
    installFetch((u) => (u.pathname.endsWith('/stops') ? resultsFor(u.searchParams.get('q')) : undefined));
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('combobox'), 'zzzz');
    expect(await screen.findByText(/No stops match/)).toBeInTheDocument();
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
  });

  it('cancels the superseded request and ignores a stale response that arrives late', async () => {
    let releaseFirst;
    const f = installFetch((u) => {
      const q = u.searchParams.get('q');
      if (q === 'roop') return new Promise((resolve) => { releaseFirst = () => resolve(resultsFor('roop')); });
      return resultsFor(q);
    });
    const user = userEvent.setup();
    render(<Harness />);
    const box = screen.getByRole('combobox');
    await user.type(box, 'roop');
    await waitFor(() => expect(stopCalls(f)).toHaveLength(1)); // slow request in flight
    await user.clear(box);
    await user.type(box, 'zzzz');
    expect(await screen.findByText(/No stops match “zzzz”/)).toBeInTheDocument();
    releaseFirst?.(); // the old answer now arrives
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
    expect(screen.getByText(/No stops match “zzzz”/)).toBeInTheDocument();
    expect(f.stub.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it('reports an error with a working Retry', async () => {
    let attempts = 0;
    installFetch((u) => {
      if (!u.pathname.endsWith('/stops')) return undefined;
      attempts += 1;
      return attempts === 1 ? { status: 503, body: { error: { code: 'database_unavailable', message: 'The GTFS database is not available.' } } } : resultsFor('roop');
    });
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('combobox'), 'roop');
    expect(await screen.findByText(/database is not available/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findAllByRole('option')).not.toHaveLength(0);
    expect(attempts).toBe(2);
  });

  it('has an accessible name and a live status region', () => {
    installFetch();
    render(<Harness />);
    expect(screen.getByRole('combobox', { name: 'From' })).toHaveAttribute('aria-autocomplete', 'list');
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
