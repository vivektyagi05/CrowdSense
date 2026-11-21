import { useEffect, useRef, useState } from 'react';
import { useStop } from '../../hooks/useStop.js';
import { availableSortOptions } from './sortOptions.js';
import { defaultDeparture, parseDeparture } from '../../lib/time.js';
import Button from '../../ui/Button.jsx';
import { DateTimeField, Select } from '../../ui/Field.jsx';
import Icon from '../../ui/Icon.jsx';
import { Notice } from '../../ui/States.jsx';
import PlacesPanel from '../places/PlacesPanel.jsx';
import { addRecent } from '../places/placesStore.js';
import StopAutocomplete from './StopAutocomplete.jsx';

/**
 * Journey search form. Stops arrive as ids (from the URL) and are resolved to real GTFS stops; an id that does not
 * exist is reported, never replaced. The form only emits {fromId, toId, departure, sort} once every value is valid.
 */
export default function JourneySearchForm({ initial = {}, onSubmit, onClear, submitLabel = 'Search journeys', problems = [] }) {
  const fromResolved = useStop(initial.fromId);
  const toResolved = useStop(initial.toId);
  const [from, setFrom] = useState(null);
  const [to, setTo] = useState(null);
  const [departure, setDeparture] = useState(initial.departure ?? defaultDeparture());
  const [sort, setSort] = useState(initial.sort ?? 'earliest');
  const [errors, setErrors] = useState({});
  const touched = useRef({ from: false, to: false });
  const formRef = useRef(null);

  useEffect(() => { if (fromResolved.stop && !touched.current.from) setFrom(fromResolved.stop); }, [fromResolved.stop]);
  useEffect(() => { if (toResolved.stop && !touched.current.to) setTo(toResolved.stop); }, [toResolved.stop]);
  useEffect(() => { if (initial.departure) setDeparture(initial.departure); }, [initial.departure]);
  useEffect(() => { if (initial.sort) setSort(initial.sort); }, [initial.sort]);

  const linkError = (resolved, id) => (id && resolved.status === 'failed' ? `Stop ${id} from this link was not found. Search for a stop instead.` : undefined);
  const fieldError = (name) => errors[name] ?? problems.find((p) => p.field === name)?.message;

  function selectFrom(stop) { touched.current.from = true; setFrom(stop); setErrors((e) => ({ ...e, from: undefined })); }
  function selectTo(stop) { touched.current.to = true; setTo(stop); setErrors((e) => ({ ...e, to: undefined })); }

  function swap() {
    touched.current = { from: true, to: true };
    setFrom(to);
    setTo(from);
  }

  function submit(e) {
    e.preventDefault();
    const next = {};
    if (!from) next.from = 'Choose a starting stop from the suggestions.';
    if (!to) next.to = 'Choose a destination stop from the suggestions.';
    if (from && to && from.stop_id === to.stop_id) next.to = 'Origin and destination must be different stops.';
    const parsed = parseDeparture(departure);
    if (!parsed.ok) next.departure = parsed.reason;
    setErrors(next);
    if (Object.keys(next).length) {
      requestAnimationFrame(() => formRef.current?.querySelector('[aria-invalid="true"]')?.focus());
      return;
    }
    addRecent(from.stop_id); addRecent(to.stop_id);   // places actually used (ids only, this device only)
    onSubmit({ fromId: from.stop_id, toId: to.stop_id, departure: parsed.value, sort });
  }

  function clear() {
    touched.current = { from: true, to: true };
    setFrom(null);
    setTo(null);
    setDeparture(defaultDeparture());
    setSort('earliest');
    setErrors({});
    onClear?.();
  }

  return (
    <>
    <form className="search-form" onSubmit={submit} noValidate ref={formRef} aria-label="Journey search">
      <div className="search-form__stops">
        <StopAutocomplete label="From" value={from} onSelect={selectFrom} error={fieldError('from') ?? linkError(fromResolved, initial.fromId)} placeholder="Origin stop" />
        <button type="button" className="icon-btn search-form__swap" onClick={swap} disabled={!from || !to} aria-label="Swap origin and destination" title={from && to ? 'Swap origin and destination' : 'Select both stops to swap them'}>
          <Icon name="swap" />
        </button>
        <StopAutocomplete label="To" value={to} onSelect={selectTo} error={fieldError('to') ?? linkError(toResolved, initial.toId)} placeholder="Destination stop" />
      </div>
      <div className="search-form__options">
        <DateTimeField label="Depart after" value={departure} onChange={(v) => { setDeparture(v); setErrors((er) => ({ ...er, departure: undefined })); }} onNow={() => setDeparture(defaultDeparture())} error={fieldError('departure')} />
        <Select label="Sort results by" value={sort} onChange={(e) => setSort(e.target.value)} options={availableSortOptions()} hint="Applied to the journeys returned by the search." />
      </div>
      <Notice tone="info" title="Direct buses only">
        The routing engine currently finds single-bus journeys. Journeys with transfers are not available yet, so there is no transfer limit to set.
      </Notice>
      <div className="search-form__actions">
        <Button type="submit" size="lg"><Icon name="search" size={18} />{submitLabel}</Button>
        <Button variant="ghost" onClick={clear}>Clear search</Button>
      </div>
    </form>
    <PlacesPanel onUse={(which, stop) => (which === 'from' ? selectFrom(stop) : selectTo(stop))} />
    </>
  );
}
