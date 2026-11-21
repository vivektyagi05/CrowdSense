import { useCallback, useSyncExternalStore } from 'react';
import { addRecent, clearAllPlaces, getSnapshot, removePlace, savePlace, subscribe, unsavePlace } from './placesStore.js';

export function usePlaces() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const isSaved = useCallback((id) => snap.state.saved.some((s) => s.id === id), [snap]);
  return {
    saved: snap.state.saved, recent: snap.state.recent, corrupted: snap.corrupted, available: snap.available,
    isSaved, save: savePlace, unsave: unsavePlace, addRecent, remove: removePlace, clearAll: clearAllPlaces,
  };
}
