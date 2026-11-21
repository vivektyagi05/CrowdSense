import { Link } from 'react-router-dom';

const REASONS = {
  webgl: 'The interactive map needs WebGL, which this browser or device does not provide.',
  init: 'The interactive map could not start.',
  engine: 'The interactive map could not be loaded (check your connection).',
};
const MAX_LISTED = 40;

/** "Map unavailable" card that still lists the real stops, so nothing is lost when the map cannot run. */
export default function MapFallback({ reason = 'init', stops = [], message }) {
  const shown = stops.slice(0, MAX_LISTED);
  return (
    <div className="map-fallback" role="status">
      <p className="map-fallback__title"><strong>Map unavailable</strong></p>
      <p className="muted">{REASONS[reason] ?? REASONS.init} {message}</p>
      {shown.length > 0 && (
        <ol className="map-fallback__list" aria-label="Stops">
          {shown.map((s) => <li key={s.id}>{s.href ? <Link to={s.href}>{s.name}</Link> : s.name}</li>)}
        </ol>
      )}
      {stops.length > MAX_LISTED && <p className="muted">and {stops.length - MAX_LISTED} more.</p>}
    </div>
  );
}
