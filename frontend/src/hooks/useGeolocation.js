import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Browser geolocation, ONLY on an explicit call to `request()` (never on mount). The position lives in React state
 * and nowhere else: no storage, no URL, no logging, no analytics (docs/phase4/OPERATIONS.md, privacy).
 * state: idle | requesting | granted | denied | unavailable | timeout | error
 */
export const GEO_OPTIONS = { enableHighAccuracy: true, timeout: 10_000, maximumAge: 0 };
export const LOW_ACCURACY_M = 200;

export function useGeolocation(geolocation = typeof navigator !== 'undefined' ? navigator.geolocation : undefined) {
  const [state, setState] = useState(geolocation ? 'idle' : 'unavailable');
  const [position, setPosition] = useState(null);   // { lat, lon, accuracy }
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const request = useCallback(() => {
    if (!geolocation) { setState('unavailable'); return; }
    setState('requesting');
    geolocation.getCurrentPosition(
      (p) => { if (!alive.current) return; setPosition({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }); setState('granted'); },
      (err) => {
        if (!alive.current) return;
        setPosition(null);
        setState(err?.code === 1 ? 'denied' : err?.code === 2 ? 'unavailable' : err?.code === 3 ? 'timeout' : 'error');
      },
      GEO_OPTIONS,
    );
  }, [geolocation]);

  const clear = useCallback(() => { setPosition(null); setState(geolocation ? 'idle' : 'unavailable'); }, [geolocation]);
  return { state, position, request, clear, lowAccuracy: Boolean(position && position.accuracy > LOW_ACCURACY_M) };
}

export const GEO_MESSAGES = {
  denied: 'Location permission was denied. You can allow it in your browser settings, or tap a point on the map instead.',
  unavailable: 'Your device could not determine a location. Tap a point on the map instead.',
  timeout: 'Finding your location took too long. Try again, or tap a point on the map instead.',
  error: 'Something went wrong while finding your location. Tap a point on the map instead.',
};
