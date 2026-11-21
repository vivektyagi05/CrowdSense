/**
 * Crowd-intelligence contract (frontend side).
 *
 * Today the backend reports `crowd: { status: "NOT_AVAILABLE", label }` for every journey, because no verified
 * ETM / e-ticketing passenger data has been obtained. Nothing in the UI computes, estimates or implies occupancy.
 *
 * When crowd data exists, a segment-level payload is expected to look like this (not rendered today):
 * @typedef {Object} SegmentCrowd
 * @property {'HISTORICAL'|'PREDICTED'} basis          which kind of estimate this is
 * @property {number|null} level                        0..1 load relative to `capacityBasis`
 * @property {number|null} confidence                   0..1
 * @property {{samples:number, days:number}|null} sampleCoverage
 * @property {string|null} freshness                    ISO timestamp of the newest contributing data
 * @property {string|null} capacityBasis                what "full" means (seated, rated capacity, ...)
 */
export const CROWD_UNAVAILABLE_TITLE = 'Historical crowd data unavailable.';
export const CROWD_UNAVAILABLE_DETAIL = 'ETM passenger data not connected.';

/** Presentation state for a journey's crowd field. Unknown statuses are reported as unknown, never guessed. */
export function describeCrowd(crowd) {
  if (!crowd || crowd.status === 'NOT_AVAILABLE') {
    return { available: false, title: CROWD_UNAVAILABLE_TITLE, detail: CROWD_UNAVAILABLE_DETAIL };
  }
  return { available: false, title: 'Crowd status not recognised.', detail: 'This version of the app cannot display that crowd status.' };
}
