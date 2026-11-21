import { durationSteps, hasActiveFilters, routesIn } from '../../lib/journeys.js';
import Button from '../../ui/Button.jsx';
import { Input, Select } from '../../ui/Field.jsx';

/**
 * Client-side filters over the complete candidate set returned by the server. Every control reflects values that exist in
 * that set (routes present, durations that would exclude something), so none of them can be a no-op.
 */
export default function JourneyFilters({ journeys, filters, onChange }) {
  const routes = routesIn(journeys);
  const steps = durationSteps(journeys);
  const set = (patch) => onChange({ ...filters, ...patch });
  return (
    <form className="filters" aria-label="Filter journeys" onSubmit={(e) => e.preventDefault()}>
      {routes.length > 1 && (
        <Select label="Bus route" value={filters.route} onChange={(e) => set({ route: e.target.value })}
          options={[{ value: '', label: 'All routes' }, ...routes.map((r) => ({ value: r.id, label: `${r.name} (${r.count})` }))]} />
      )}
      {steps.length > 0 && (
        <Select label="Longest journey" value={filters.maxDuration ?? ''} onChange={(e) => set({ maxDuration: e.target.value ? Number(e.target.value) : null })}
          options={[{ value: '', label: 'Any duration' }, ...steps.map((s) => ({ value: s, label: `Up to ${s} min` }))]} />
      )}
      <Input label="Departs no earlier than" type="time" value={filters.departFrom} onChange={(e) => set({ departFrom: e.target.value })} />
      <Input label="Departs no later than" type="time" value={filters.departTo} onChange={(e) => set({ departTo: e.target.value })} />
      {hasActiveFilters(filters) && <Button variant="ghost" size="sm" onClick={() => onChange({ route: '', maxDuration: null, departFrom: '', departTo: '' })}>Clear filters</Button>}
    </form>
  );
}
