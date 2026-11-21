import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { clearCache } from '../api/cache.js';
import { resetPlacesCache } from '../features/places/placesStore.js';

// jsdom has no <dialog> behaviour; emulate the parts the Modal relies on.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal() { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function close() { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); };
}
window.scrollTo = () => {};

afterEach(() => {
  cleanup();
  clearCache();
  try { window.localStorage.clear(); } catch { /* ignore */ }
  resetPlacesCache();   // per-test isolation of the device-local places store
  vi.unstubAllGlobals();
});
