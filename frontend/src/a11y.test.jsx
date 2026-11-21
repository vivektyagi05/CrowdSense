import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { installFetch, renderApp } from './test/harness.jsx';

const PAGES = [
  ['/', 'Know the crowd before you board.'],
  ['/journeys?from=106&to=216&departure=2026-11-11T05:00', /Banglow Road/],
  ['/journeys/72_06_40?from=106&to=216&date=2026-11-11&board=06%3A56%3A26', /Banglow Road/],
  ['/explore', 'Explore the Delhi bus network'],
  ['/stops/271', 'GGS University ISBT Kashmere Gate'],
  ['/routes/72', '114UP'],
  ['/insights', 'Network insights'],
  ['/about', 'About CrowdSense and its data'],
];

describe('accessibility basics on every page', () => {
  it.each(PAGES)('%s has one h1, a skip link, landmarks, and every control is named', async (path, h1) => {
    installFetch();
    renderApp(path);
    await screen.findByRole('heading', { level: 1, name: h1 });
    await new Promise((r) => setTimeout(r, 400)); // let secondary requests settle
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main');
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    const unnamed = [...document.querySelectorAll('button, a[href], input, select')].filter((el) => {
      if (el.type === 'hidden') return false;
      const name = el.getAttribute('aria-label') || el.labels?.[0]?.textContent || el.textContent?.trim() || el.getAttribute('title');
      return !name;
    });
    expect(unnamed.map((e) => e.outerHTML.slice(0, 80))).toEqual([]);
    expect(document.querySelectorAll('a[href="#"]')).toHaveLength(0);
  });

  it('moves focus to the main region and updates the title when navigating', async () => {
    installFetch();
    const { user } = renderApp('/');
    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('link', { name: 'About the data' }));
    await screen.findByRole('heading', { level: 1, name: 'About CrowdSense and its data' });
    expect(screen.getByRole('main')).toHaveFocus();
    expect(document.title).toBe('About the data · CrowdSense');
  });

  it('announces form validation errors as alerts and focuses the first invalid field', async () => {
    installFetch();
    const { user } = renderApp('/');
    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /Search journeys/ }));
    expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
    await new Promise((r) => requestAnimationFrame(r));
    expect(screen.getByRole('combobox', { name: 'From' })).toHaveFocus();
    expect(screen.getByRole('combobox', { name: 'From' })).toHaveAttribute('aria-invalid', 'true');
  });
});
