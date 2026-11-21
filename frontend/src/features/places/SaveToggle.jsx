import { useState } from 'react';
import Button from '../../ui/Button.jsx';
import { MAX_SAVED } from './placesStore.js';
import { usePlaces } from './usePlaces.js';

/** Save/unsave one stop (by id). Reports a full list or an unavailable store honestly. */
export default function SaveToggle({ stopId }) {
  const places = usePlaces();
  const [msg, setMsg] = useState('');
  const saved = places.isSaved(stopId);
  function toggle() {
    if (saved) { places.unsave(stopId); setMsg(''); return; }
    const r = places.save(stopId);
    setMsg(r.ok ? '' : r.reason === 'full' ? `You can save up to ${MAX_SAVED} places. Remove one first.` : 'This browser would not let CrowdSense save on this device.');
  }
  return (
    <span className="save-toggle">
      <Button variant="secondary" size="sm" aria-pressed={saved} onClick={toggle}>{saved ? 'Saved on this device' : 'Save this place'}</Button>
      {msg && <span role="status" className="muted"> {msg}</span>}
    </span>
  );
}
