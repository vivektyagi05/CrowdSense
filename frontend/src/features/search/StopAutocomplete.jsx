import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { smartSearchStops } from '../../api/endpoints.js';
import { useAsync } from '../../hooks/useAsync.js';
import { useDebouncedValue } from '../../hooks/useDebouncedValue.js';
import { relativeToCentre } from '../../lib/geo.js';
import Icon from '../../ui/Icon.jsx';

export const MIN_QUERY_LENGTH = 2;
export const DEBOUNCE_MS = 250;
const RESULT_LIMIT = 8;

/**
 * Rows for the listbox. A smart-search response has `groups` (place clusters); a Phase 3 style response only `items`.
 * Group headings are NOT options: only a specific stop can be chosen (the router cannot search 'any stop at this place').
 */
export function buildRows(data) {
  if (!data) return { rows: [], options: [] };
  if (!Array.isArray(data.groups)) {
    const options = (data.items ?? []).map((stop) => ({ stop, group: null }));
    return { rows: options.map((o, i) => ({ kind: 'option', ...o, index: i })), options };
  }
  const rows = []; const options = [];
  for (const group of data.groups) {
    const multi = group.members.length > 1;
    if (multi) rows.push({ kind: 'heading', group });
    for (const stop of group.members) {
      const o = { stop, group: multi ? group : null, fuzzy: stop.match_type === 'fuzzy' };
      rows.push({ kind: 'option', ...o, index: options.length });
      options.push(o);
    }
  }
  return { rows, options };
}

/**
 * Stop picker. The text box holds what the passenger typed; `value` holds the *selected GTFS stop* (or null). Only a
 * selected stop counts: editing the text after selecting discards the selection, so free text can never be submitted
 * as a stop. Implements the ARIA 1.2 combobox + listbox pattern (focus stays in the input; arrows move an
 * aria-activedescendant).
 *
 * Requests: debounced, cancelled when superseded (useAsync aborts the previous one, and a response for an old key is
 * ignored), and only sent for queries of MIN_QUERY_LENGTH+ characters.
 */
export default function StopAutocomplete({ label, value, onSelect, error, placeholder = 'Search stop name' }) {
  const uid = useId();
  const inputRef = useRef(null);
  const rootRef = useRef(null);
  const clearedByUs = useRef(false);
  const [text, setText] = useState(value?.stop_name ?? '');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  // Mirror external changes (swap, URL restore, form reset) into the text box, but never fight the user's typing.
  useEffect(() => {
    if (value) setText(value.stop_name ?? value.stop_id);
    else if (!clearedByUs.current) setText('');
    clearedByUs.current = false;
  }, [value]);

  const trimmed = text.trim();
  const debounced = useDebouncedValue(trimmed, DEBOUNCE_MS);
  const searching = open && !value && debounced.length >= MIN_QUERY_LENGTH && debounced === trimmed;
  const query = useAsync(searching ? `q:${debounced}` : null, (signal) => smartSearchStops({ q: debounced, limit: RESULT_LIMIT }, { signal }));
  const built = useMemo(() => buildRows(query.data), [query.data]);
  const results = built.options.map((o) => o.stop);
  const waiting = open && !value && trimmed.length >= MIN_QUERY_LENGTH && (debounced !== trimmed || query.status === 'loading');

  useEffect(() => setActive(-1), [query.data]);

  const listId = `${uid}-list`;
  const optionId = (i) => `${uid}-opt-${i}`;
  const showList = open && !value && trimmed.length > 0;

  function choose(stop) {
    onSelect(stop);
    setText(stop.stop_name);
    setOpen(false);
    setActive(-1);
  }

  function onChange(e) {
    setText(e.target.value);
    setOpen(true);
    if (value) {
      clearedByUs.current = true;
      onSelect(null);
    }
  }

  function clear() {
    clearedByUs.current = true;
    setText('');
    setOpen(false);
    if (value) onSelect(null);
    inputRef.current?.focus();
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      if (results.length) setActive((a) => (a + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (results.length) setActive((a) => (a <= 0 ? results.length - 1 : a - 1));
    } else if (e.key === 'Enter') {
      if (showList && active >= 0 && results[active]) {
        e.preventDefault(); // choose the option, do not submit the form
        choose(results[active]);
      }
    } else if (e.key === 'Escape') {
      if (open) { e.preventDefault(); setOpen(false); }
    }
  }

  function onBlur(e) {
    if (!rootRef.current?.contains(e.relatedTarget)) setOpen(false);
  }

  let status = null;
  if (showList) {
    if (trimmed.length < MIN_QUERY_LENGTH) status = `Type at least ${MIN_QUERY_LENGTH} letters to search.`;
    else if (waiting) status = 'Searching stops…';
    else if (query.status === 'ready' && results.length === 0) status = `No stops match “${debounced}”.`;
    else if (query.status === 'ready') { const total = query.data.total ?? query.data.total_groups ?? results.length; const shown = Array.isArray(query.data.groups) ? query.data.returned_groups : results.length; status = `${results.length} stop${results.length === 1 ? '' : 's'} found${total > shown ? ` (showing the first ${shown} of ${total}; type more to narrow)` : ''}.`; }
  }

  return (
    <div className={`field stop-field ${error ? 'field--invalid' : ''}`} ref={rootRef} onBlur={onBlur}>
      <label className="field__label" htmlFor={`${uid}-input`}>{label}</label>
      <div className={`combo ${value ? 'combo--selected' : ''}`}>
        <Icon name="pin" size={18} className="combo__lead" />
        <input
          ref={inputRef} id={`${uid}-input`} className="control combo__input" type="text" role="combobox" autoComplete="off" spellCheck="false"
          aria-expanded={showList} aria-controls={listId} aria-autocomplete="list" aria-activedescendant={active >= 0 ? optionId(active) : undefined}
          aria-invalid={error ? true : undefined} aria-describedby={`${uid}-status${error ? ` ${uid}-error` : ''}`}
          placeholder={placeholder} value={text} onChange={onChange} onKeyDown={onKeyDown} onFocus={() => setOpen(true)}
        />
        {text && <button type="button" className="combo__clear" onClick={clear} aria-label={`Clear ${label.toLowerCase()}`}><Icon name="close" size={16} /></button>}
        {showList && (
          <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="combo__list" hidden={!results.length}>
            {built.rows.map((row) => (row.kind === 'heading' ? (
              <li key={`h-${row.group.cluster_id ?? row.group.display_name}`} role="presentation" className="combo__group">
                <strong>{row.group.display_name}</strong> <span className="muted">· {row.group.members.length} stops at this place. Choose the one you board at.</span>
              </li>
            ) : (
              <li
                key={row.stop.stop_id} id={optionId(row.index)} role="option" aria-selected={row.index === active} className={`combo__option ${row.group ? 'combo__option--member' : ''} ${row.index === active ? 'is-active' : ''}`}
                onMouseDown={(e) => e.preventDefault()} onClick={() => choose(row.stop)} onMouseMove={() => setActive(row.index)}
              >
                <span className="combo__name">{row.stop.stop_name}{row.fuzzy ? <span className="combo__tag"> similar spelling</span> : null}</span>
                <span className="combo__meta tnum">
                  Stop {row.stop.stop_id} · {row.stop.stop_lat.toFixed(4)}, {row.stop.stop_lon.toFixed(4)}
                  {row.stop.route_names?.length ? ` · routes ${row.stop.route_names.join(', ')}${row.stop.routes_count > row.stop.route_names.length ? ` +${row.stop.routes_count - row.stop.route_names.length}` : ''}` : ''}
                  {row.group && relativeToCentre(row.group, row.stop) ? ` · ${relativeToCentre(row.group, row.stop)}` : ''}
                </span>
              </li>
            )))}
          </ul>
        )}
      </div>
      {showList && query.status === 'failed' && (
        <div className="combo__status combo__status--error" role="alert">
          {query.error.message}{' '}
          <button type="button" className="link-btn" onClick={query.retry}>Retry</button>
        </div>
      )}
      <p id={`${uid}-status`} className="combo__status" role="status" aria-live="polite">{query.status === 'failed' ? '' : status}</p>
      {value ? (
        <p className="field__selected tnum"><Icon name="check" size={14} /> Selected stop {value.stop_id}</p>
      ) : trimmed ? (
        <p className="field__hint">Pick a stop from the list to use it.</p>
      ) : null}
      {error && <p id={`${uid}-error`} className="field__error" role="alert">{error}</p>}
    </div>
  );
}
