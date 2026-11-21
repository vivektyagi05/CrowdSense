import { useStop } from '../../hooks/useStop.js';
import Button from '../../ui/Button.jsx';
import { MAX_RECENT, MAX_SAVED } from './placesStore.js';
import { usePlaces } from './usePlaces.js';
import './places.css';

/**
 * Saved and recent places. Each row's stop id is VALIDATED against the API when shown: a stop that no longer exists
 * is reported honestly and can be removed. `onUse(which, stop)` fills the journey form with the real stop record.
 */
export default function PlacesPanel({ onUse }) {
  const places = usePlaces();
  const { saved, recent } = places;
  const recentOnly = recent.filter((r) => !saved.some((s) => s.id === r.id));
  if (!places.available && !saved.length && !recent.length) return null;
  if (!saved.length && !recentOnly.length && !places.corrupted) return null;
  return (
    <section className="places" aria-labelledby="places-title">
      <div className="places__head">
        <h2 id="places-title">Your places</h2>
        <span className="muted">Stored on this device only. Stop ids only; nothing is sent anywhere.</span>
        {(saved.length > 0 || recentOnly.length > 0) && <Button variant="ghost" size="sm" onClick={places.clearAll}>Clear all saved and recent places</Button>}
      </div>
      {places.corrupted && <p className="map-geo-note" role="status">Saved places on this device could not be read, so they were ignored. New places will replace them.</p>}
      {saved.length > 0 && <PlaceGroup title={`Saved (${saved.length} of ${MAX_SAVED})`} entries={saved} places={places} onUse={onUse} />}
      {recentOnly.length > 0 && <PlaceGroup title={`Recent (up to ${MAX_RECENT})`} entries={recentOnly} places={places} onUse={onUse} />}
    </section>
  );
}

function PlaceGroup({ title, entries, places, onUse }) {
  return (
    <div>
      <h3 className="places__group">{title}</h3>
      <ul className="places__list">{entries.map((e) => <PlaceRow key={e.id} id={e.id} places={places} onUse={onUse} />)}</ul>
    </div>
  );
}

function PlaceRow({ id, places, onUse }) {
  const { stop, status, error, retry } = useStop(id);
  const saved = places.isSaved(id);
  if (status === 'loading') return <li className="places__row muted">Checking stop {id}…</li>;
  if (status === 'failed' && error?.status === 404) {
    return (
      <li className="places__row">
        <span>Stop {id} is no longer in the timetable.</span>
        <Button size="sm" variant="secondary" onClick={() => places.remove(id)} aria-label={`Remove stop ${id} from your places`}>Remove</Button>
      </li>
    );
  }
  if (status === 'failed') {
    return (
      <li className="places__row">
        <span>Could not check stop {id}: {error?.message}</span>
        <Button size="sm" variant="secondary" onClick={retry}>Retry</Button>
        <Button size="sm" variant="ghost" onClick={() => places.remove(id)} aria-label={`Remove stop ${id} from your places`}>Remove</Button>
      </li>
    );
  }
  if (!stop) return null;
  return (
    <li className="places__row">
      <span className="places__name"><strong>{stop.stop_name}</strong> <span className="muted tnum">stop {stop.stop_id}</span></span>
      <span className="places__actions">
        <Button size="sm" variant="secondary" onClick={() => onUse?.('from', stop)} aria-label={`Use ${stop.stop_name} as origin`}>From</Button>
        <Button size="sm" variant="secondary" onClick={() => onUse?.('to', stop)} aria-label={`Use ${stop.stop_name} as destination`}>To</Button>
        {!saved && <Button size="sm" variant="ghost" onClick={() => places.save(id)} aria-label={`Save ${stop.stop_name}`}>Save</Button>}
        <Button size="sm" variant="ghost" onClick={() => places.remove(id)} aria-label={`Remove ${stop.stop_name} from your places`}>Remove</Button>
      </span>
    </li>
  );
}
