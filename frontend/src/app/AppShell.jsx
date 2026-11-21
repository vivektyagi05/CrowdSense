import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useBackendStatus } from '../hooks/useBackendStatus.js';
import Icon from '../ui/Icon.jsx';
import { Notice } from '../ui/States.jsx';
import { ToastProvider } from '../ui/Toast.jsx';

const NAV = [
  { to: '/', label: 'Plan a journey', end: true },
  { to: '/explore', label: 'Explore network' },
  { to: '/insights', label: 'Insights' },
  { to: '/about', label: 'About the data' },
];

function Logo() {
  return (
    <Link to="/" className="logo" aria-label="CrowdSense home">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#0e2a1f" /><path d="M8 21V11m8 10V8m8 13v-7" stroke="#34d399" strokeWidth="3" strokeLinecap="round" /></svg>
      <span>CrowdSense</span>
    </Link>
  );
}

export default function AppShell() {
  const backend = useBackendStatus();
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const mainRef = useRef(null);
  const first = useRef(true);

  // On client-side navigation: close the mobile menu, return to the top and move focus to the new page.
  useEffect(() => {
    setMenuOpen(false);
    if (first.current) { first.current = false; return; }
    window.scrollTo?.(0, 0);
    mainRef.current?.focus({ preventScroll: true });
  }, [pathname]);

  return (
    <ToastProvider>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="site-header__inner">
          <Logo />
          <button type="button" className="icon-btn site-header__menu" aria-expanded={menuOpen} aria-controls="primary-nav" aria-label={menuOpen ? 'Close menu' : 'Open menu'} onClick={() => setMenuOpen((o) => !o)}>
            <Icon name={menuOpen ? 'close' : 'menu'} />
          </button>
          <nav id="primary-nav" aria-label="Primary" className={`site-nav ${menuOpen ? 'is-open' : ''}`}>
            {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.end} className="site-nav__link">{n.label}</NavLink>)}
          </nav>
        </div>
      </header>
      {backend.state !== 'ready' && backend.state !== 'checking' && (
        <div className="backend-banner" role="alert">
          <div className="container">
            {backend.message}{' '}
            <button type="button" className="link-btn" onClick={backend.retry}>Retry</button>
          </div>
        </div>
      )}
      <main id="main" ref={mainRef} tabIndex={-1} className="main">
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="container site-footer__inner">
          <p><strong>Know the crowd before you board.</strong> Schedules come from Delhi static GTFS. Crowd data and live arrivals are not connected.</p>
          <Notice tone="info">Times are scheduled, not live. Real buses may run early, late or not at all.</Notice>
        </div>
      </footer>
    </ToastProvider>
  );
}
