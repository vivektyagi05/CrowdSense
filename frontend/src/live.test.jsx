// Live integration test: drives the real UI against the REAL backend and the REAL Delhi GTFS database.
// Skipped unless CROWDSENSE_LIVE_API is set (e.g. http://127.0.0.1:8000/api/v1). This runs in jsdom, not a browser.
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from './test/harness.jsx';

const live = process.env.CROWDSENSE_LIVE_API;
describe.skipIf(!live)('live backend', () => {
  it('home -> stop search -> real journeys -> details -> route -> stop', async () => {
    const { user } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Know the crowd before you board.' });
    expect(await screen.findByText('6,812')).toBeInTheDocument();
    const pick = async (label, text) => {
      await user.type(screen.getByRole('combobox', { name: label }), text);
      const list = await screen.findByRole('listbox', {}, { timeout: 5000 });
      return user.click(within(list).getAllByRole('option').find((o) => o.textContent.includes(label === 'From' ? 'Stop 106 ' : 'Stop 216 ')));
    };
    await pick('From', 'banglow road');
    await pick('To', 'alpana');
    const day = '2026-11-11'; // a date inside the feed calendar
    const { fireEvent } = await import('@testing-library/react');
    fireEvent.change(screen.getByLabelText('Depart after: date'), { target: { value: day } });
    fireEvent.change(screen.getByLabelText('Depart after: time'), { target: { value: '05:00' } });
    await user.click(screen.getByRole('button', { name: /Search journeys/ }));
    expect(await screen.findByRole('heading', { level: 2, name: /^\d+ journeys?$/ }, { timeout: 15000 })).toBeInTheDocument();
    const first = screen.getAllByRole('article')[0];
    expect(within(first).getByText('06:56')).toBeInTheDocument();
    await user.click(within(first).getByRole('link', { name: 'View journey' }));
    expect(await screen.findByText('Trip 72_06_40', {}, { timeout: 15000 })).toBeInTheDocument();
    expect(screen.getByText('7 intermediate stops')).toBeInTheDocument();
    await user.click(screen.getAllByRole('link', { name: 'Route 114UP' })[0]);
    expect(await screen.findByRole('heading', { level: 1, name: '114UP' }, { timeout: 15000 })).toBeInTheDocument();
    expect(await screen.findByText(/Stops of trip/i, {}, { timeout: 15000 })).toBeInTheDocument();
  }, 60000);
});
