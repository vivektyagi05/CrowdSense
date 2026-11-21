// Small in-memory cache for *reference data* that never changes during a session (feed summary, agencies, a stop's
// own record). It de-duplicates in-flight requests too, so React StrictMode's double mount or two components asking for
// the same record cost one network call. Failed requests are never cached. Shared promises are not abortable by one
// caller, so cached loaders ignore AbortSignals by design.
const entries = new Map();
const MAX_ENTRIES = 500;

export function cached(key, load) {
  if (entries.has(key)) return entries.get(key);
  const promise = load().catch((err) => {
    entries.delete(key);
    throw err;
  });
  if (entries.size >= MAX_ENTRIES) entries.delete(entries.keys().next().value);
  entries.set(key, promise);
  return promise;
}

export const clearCache = () => entries.clear();
