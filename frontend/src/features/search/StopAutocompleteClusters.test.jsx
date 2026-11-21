import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { installFetch } from '../../test/harness.jsx';
import StopAutocomplete, { buildRows } from './StopAutocomplete.jsx';

const member = (id, name, lat, lon, routes, extra = {}) => ({ stop_id: id, stop_name: name, stop_lat: lat, stop_lon: lon, routes_count: routes.length, route_names: routes, match_type: 'prefix', score: 790, ...extra });
const rithala = { cluster_id: 'c_aaa', display_name: 'Rithala Metro Station', stop_count: 2, centroid_lat: 28.7200, centroid_lon: 77.1000, match_type: 'prefix', score: 790,
  members: [member('15', 'Rithala Metro Station', 28.72030, 77.1000, ['138DOWN', '250UP']), member('83', 'Rithala Metro Station', 28.71970, 77.1000, ['138UP'], { routes_count: 6 })] };
const single = { cluster_id: 'c_bbb', display_name: 'Rithala Village', stop_count: 1, centroid_lat: 28.73, centroid_lon: 77.11, match_type: 'fuzzy', score: 480, members: [member('900', 'Rithala Village', 28.73, 77.11, ['5'], { match_type: 'fuzzy' })] };
const smart = { query: 'rithala', mode: 'smart', limit: 8, total_groups: 2, returned_groups: 2, groups: [rithala, single], items: [], notice: null };

function Harness({ onSelect }) {
  const [stop, setStop] = useState(null);
  return <StopAutocomplete label="From" value={stop} onSelect={(s) => { setStop(s); onSelect?.(s); }} />;
}
const serve = (body) => installFetch((u) => (u.pathname.endsWith('/stops') ? { status: 200, body } : undefined));

describe('cluster-aware autocomplete', () => {
  it('asks for the smart, cluster-grouped search', async () => {
    const f = serve(smart);
    const user = userEvent.setup(); render(<Harness />);
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'rithala');
    await screen.findAllByRole('option');
    const call = f.calls.find((u) => u.pathname.endsWith('/stops'));
    expect(call.searchParams.get('mode')).toBe('smart'); expect(call.searchParams.get('q')).toBe('rithala');
  });

  it('shows a place with several stops as a heading plus one selectable row per REAL stop with distinguishing data; the heading is not an option', async () => {
    serve(smart);
    const user = userEvent.setup(); render(<Harness />);
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'rithala');
    const options = await screen.findAllByRole('option');
    expect(options).toHaveLength(3);                                          // 2 stops of the cluster + 1 single; the heading is not an option
    const list = screen.getByRole('listbox', { name: 'From suggestions' });
    expect(within(list).getByText('Rithala Metro Station', { selector: 'strong' })).toBeInTheDocument();
    expect(within(list).getByText(/2 stops at this place. Choose the one you board at/)).toBeInTheDocument();
    expect(options[0]).toHaveTextContent('Stop 15'); expect(options[0]).toHaveTextContent('routes 138DOWN, 250UP');
    expect(options[0]).toHaveTextContent('33 m north of the place centre');
    expect(options[1]).toHaveTextContent('Stop 83'); expect(options[1]).toHaveTextContent('routes 138UP +5');
    expect(options[1]).toHaveTextContent('south of the place centre');
    expect(options[0].textContent).not.toMatch(/towards/i);                   // no invented direction labels
    expect(screen.queryByRole('option', { name: /any stop|all stops/i })).not.toBeInTheDocument();
  });

  it('selecting a member selects that specific stop (a real GTFS stop object)', async () => {
    serve(smart);
    const onSelect = vi.fn();
    const user = userEvent.setup(); render(<Harness onSelect={onSelect} />);
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'rithala');
    await user.click((await screen.findAllByRole('option'))[1]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0]).toMatchObject({ stop_id: '83', stop_name: 'Rithala Metro Station' });
    expect(screen.getByText('Selected stop 83')).toBeInTheDocument();
  });

  it('keyboard: ArrowDown skips headings, lands on members in order; Enter selects the member', async () => {
    serve(smart);
    const onSelect = vi.fn();
    const user = userEvent.setup(); render(<Harness onSelect={onSelect} />);
    const box = screen.getByRole('combobox', { name: 'From' });
    await user.type(box, 'rithala');
    await screen.findAllByRole('option');
    await user.keyboard('{ArrowDown}');
    expect(box).toHaveAttribute('aria-activedescendant', screen.getAllByRole('option')[0].id);
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{ArrowUp}{Enter}');
    expect(onSelect.mock.calls[0][0].stop_id).toBe('83');
  });

  it('flags a spelling-tolerant match honestly', async () => {
    serve(smart);
    const user = userEvent.setup(); render(<Harness />);
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'rithala');
    const opts = await screen.findAllByRole('option');
    expect(opts[2]).toHaveTextContent('similar spelling'); expect(opts[0]).not.toHaveTextContent('similar spelling');
  });

  it('a single-stop place has no heading', async () => {
    serve({ ...smart, groups: [single], total_groups: 1, returned_groups: 1 });
    const user = userEvent.setup(); render(<Harness />);
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'rithala');
    await screen.findAllByRole('option');
    expect(screen.queryByText(/stops at this place/)).not.toBeInTheDocument();
  });

  it('empty smart result and Devanagari-style no-match say so', async () => {
    serve({ ...smart, groups: [], items: [], total_groups: 0, returned_groups: 0, notice: 'No stop matches.' });
    const user = userEvent.setup(); render(<Harness />);
    await user.type(screen.getByRole('combobox', { name: 'From' }), 'कश्मीरी');
    expect(await screen.findByText(/No stops match/)).toBeInTheDocument();
  });

  it('buildRows: legacy (items-only) responses stay flat; groups produce headings only for multi-stop places', () => {
    expect(buildRows({ items: [{ stop_id: 'a' }, { stop_id: 'b' }] }).rows.map((r) => r.kind)).toEqual(['option', 'option']);
    expect(buildRows(smart).rows.map((r) => r.kind)).toEqual(['heading', 'option', 'option', 'option']);
    expect(buildRows(null)).toEqual({ rows: [], options: [] });
  });
});
