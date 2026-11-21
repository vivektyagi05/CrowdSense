// Saved + recent places, stored ON THIS DEVICE ONLY (localStorage). Stop IDs only: no names, no coordinates, no
// positions. Every storage access is wrapped: private mode, a full quota, a blocked store or corrupted JSON must
// degrade to "nothing saved", never to a crash.
export const STORAGE_KEY = 'crowdsense.places.v1';
export const SCHEMA_VERSION = 1;
export const MAX_RECENT = 20;
export const MAX_SAVED = 10;
const MAX_ID_LENGTH = 255;

const empty = () => ({ version: SCHEMA_VERSION, saved: [], recent: [] });
const listeners = new Set();
let snapshot = null; // { state, corrupted, available }

const validId = (v) => typeof v === 'string' && v.length > 0 && v.length <= MAX_ID_LENGTH;

/** Keep only well-formed entries, de-dupe by id (first wins), enforce the caps. Never throws. */
export function sanitize(raw) {
  if (!raw || typeof raw !== 'object' || raw.version !== SCHEMA_VERSION) return { state: empty(), ok: false };
  const clean = (list, cap) => {
    const seen = new Set(); const out = [];
    for (const e of Array.isArray(list) ? list : []) {
      const id = typeof e === 'string' ? e : e?.id;
      if (!validId(id) || seen.has(id)) continue;
      seen.add(id); out.push({ id, at: typeof e?.at === 'string' ? e.at.slice(0, 40) : '' });
      if (out.length >= cap) break;
    }
    return out;
  };
  const saved = clean(raw.saved, MAX_SAVED);
  const savedIds = new Set(saved.map((s) => s.id));
  return { state: { version: SCHEMA_VERSION, saved, recent: clean(raw.recent, MAX_RECENT).filter((r) => !savedIds.has(r.id) || true) }, ok: true };
}

function storage() {
  try { return typeof window !== 'undefined' ? window.localStorage : null; } catch { return null; }
}

function load() {
  const ls = storage();
  if (!ls) return { state: empty(), corrupted: false, available: false };
  try {
    const text = ls.getItem(STORAGE_KEY);
    if (text == null) return { state: empty(), corrupted: false, available: true };
    const { state, ok } = sanitize(JSON.parse(text));
    return { state, corrupted: !ok, available: true };
  } catch {
    return { state: empty(), corrupted: true, available: true };
  }
}

function persist(state) {
  const ls = storage();
  if (!ls) return false;
  try { ls.setItem(STORAGE_KEY, JSON.stringify(state)); return true; } catch { return false; }
}

export function getSnapshot() {
  if (!snapshot) snapshot = load();
  return snapshot;
}
function emit() { snapshot = null; listeners.forEach((l) => l()); }
export function subscribe(listener) {
  listeners.add(listener);
  const onStorage = (e) => { if (e.key === STORAGE_KEY || e.key === null) emit(); };
  if (typeof window !== 'undefined') window.addEventListener('storage', onStorage);
  return () => { listeners.delete(listener); if (typeof window !== 'undefined') window.removeEventListener('storage', onStorage); };
}

/** Test helper: forget the cached snapshot. */
export function resetPlacesCache() { snapshot = null; }

const now = () => new Date().toISOString();

function mutate(fn) {
  const { state } = getSnapshot();
  const next = fn({ version: SCHEMA_VERSION, saved: [...state.saved], recent: [...state.recent] });
  const stored = persist(next);
  emit();
  return stored;
}

export function addRecent(id) {
  if (!validId(id)) return false;
  return mutate((s) => { s.recent = [{ id, at: now() }, ...s.recent.filter((r) => r.id !== id)].slice(0, MAX_RECENT); return s; });
}

/** { ok: true } | { ok: false, reason: 'full' | 'invalid' | 'storage' } */
export function savePlace(id) {
  if (!validId(id)) return { ok: false, reason: 'invalid' };
  const { state } = getSnapshot();
  if (state.saved.some((s) => s.id === id)) return { ok: true };
  if (state.saved.length >= MAX_SAVED) return { ok: false, reason: 'full' };
  const stored = mutate((s) => { s.saved = [{ id, at: now() }, ...s.saved]; return s; });
  return stored ? { ok: true } : { ok: false, reason: 'storage' };
}

export const unsavePlace = (id) => mutate((s) => { s.saved = s.saved.filter((x) => x.id !== id); return s; });
export const removePlace = (id) => mutate((s) => { s.saved = s.saved.filter((x) => x.id !== id); s.recent = s.recent.filter((x) => x.id !== id); return s; });
export const clearAllPlaces = () => mutate(() => empty());
