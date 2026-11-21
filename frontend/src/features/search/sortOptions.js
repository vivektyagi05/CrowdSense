import { availableSorts } from '../../lib/journeys.js';

// Before any results exist only the orderings that make sense for single-bus journeys are offered
// (fewest-transfers / balanced become available when a result set actually contains different transfer counts).
export const availableSortOptions = () => availableSorts([]);
