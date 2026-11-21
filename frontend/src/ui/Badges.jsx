import { Link } from 'react-router-dom';

/** Route number as it appears on the bus: a fixed-width-feeling tile, optionally a link to the route page. */
export function RouteBadge({ id, name, to = id != null ? `/routes/${encodeURIComponent(id)}` : null }) {
  const label = name || id;
  const inner = <span className="route-badge tnum">{label}</span>;
  return to ? <Link className="route-badge-link" to={to} aria-label={`Route ${label}`}>{inner}</Link> : inner;
}

/** tone: neutral | success | warning | danger | info */
export function StatusBadge({ tone = 'neutral', children }) {
  return <span className={`status-badge status-badge--${tone}`}>{children}</span>;
}
