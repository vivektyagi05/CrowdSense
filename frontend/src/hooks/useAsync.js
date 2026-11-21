import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client.js';

/**
 * Runs `load(signal)` whenever `key` changes and tracks its outcome.
 * status: 'idle' (no key) | 'loading' | 'ready' | 'failed'. Aborted requests are ignored, so a stale response can
 * never overwrite a newer one. `retry()` re-runs the same load. `keepPrevious` keeps the last data visible while the
 * next request loads (used for pagination so the list does not flash empty).
 */
export function useAsync(key, load, { keepPrevious = false } = {}) {
  const [state, setState] = useState({ status: key == null ? 'idle' : 'loading', data: null, error: null });
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (key == null) {
      setState({ status: 'idle', data: null, error: null });
      return undefined;
    }
    const controller = new AbortController();
    setState((prev) => ({ status: 'loading', data: keepPrevious ? prev.data : null, error: null }));
    loadRef.current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ status: 'ready', data, error: null });
      })
      .catch((error) => {
        if (controller.signal.aborted || (error instanceof ApiError && error.kind === 'aborted')) return;
        setState({ status: 'failed', data: null, error });
      });
    return () => controller.abort();
  }, [key, attempt, keepPrevious]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}
