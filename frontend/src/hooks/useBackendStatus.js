import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../api/client.js';
import { fetchHealth } from '../api/endpoints.js';
import { API_BASE_URL } from '../config.js';

/**
 * Checks backend readiness once on mount (and on retry).
 * state: 'checking' | 'ready' | 'unreachable' | 'needs_setup' | 'error'
 */
export function useBackendStatus() {
  const [status, setStatus] = useState({ state: 'checking', message: '' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus({ state: 'checking', message: '' });
    fetchHealth({ signal: controller.signal })
      .then((health) => {
        if (health.status === 'ok') setStatus({ state: 'ready', message: '' });
        else if (health.status === 'needs_setup')
          setStatus({ state: 'needs_setup', message: 'The backend is running, but the GTFS database is not ready. Run the GTFS import (see README), then retry.' });
        else setStatus({ state: 'error', message: 'The backend is running but its database reported an error. Check the backend logs.' });
      })
      .catch((err) => {
        if (err instanceof ApiError && err.kind === 'aborted') return;
        setStatus({ state: 'unreachable', message: `Cannot reach the backend at ${API_BASE_URL}. Start it (python -m app) and retry.` });
      });
    return () => controller.abort();
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...status, retry };
}
