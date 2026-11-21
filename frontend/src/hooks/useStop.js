import { getStop } from '../api/endpoints.js';
import { useAsync } from './useAsync.js';

/** Resolve one stop id to its record (cached). status: idle | loading | ready | failed. */
export function useStop(stopId) {
  const r = useAsync(stopId ? `stop:${stopId}` : null, () => getStop(stopId));
  return { stop: r.data, status: r.status, error: r.error, retry: r.retry };
}
