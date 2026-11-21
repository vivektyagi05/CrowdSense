import { useRef } from 'react';

/** Accessible tab list (WAI-ARIA tabs pattern: arrow keys move and activate, Home/End jump). tabs: [{id, label}] */
export function Tabs({ tabs, value, onChange, label, idPrefix = 'tab' }) {
  const refs = useRef({});
  const move = (index) => {
    const next = tabs[(index + tabs.length) % tabs.length];
    onChange(next.id);
    refs.current[next.id]?.focus();
  };
  const onKeyDown = (e, i) => {
    if (e.key === 'ArrowRight') { e.preventDefault(); move(i + 1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); move(i - 1); }
    else if (e.key === 'Home') { e.preventDefault(); move(0); }
    else if (e.key === 'End') { e.preventDefault(); move(tabs.length - 1); }
  };
  return (
    <div role="tablist" aria-label={label} className="tabs">
      {tabs.map((t, i) => (
        <button
          key={t.id} ref={(el) => { refs.current[t.id] = el; }} type="button" role="tab" id={`${idPrefix}-${t.id}`}
          aria-selected={value === t.id} aria-controls={`${idPrefix}-panel-${t.id}`} tabIndex={value === t.id ? 0 : -1}
          className="tabs__tab" onClick={() => onChange(t.id)} onKeyDown={(e) => onKeyDown(e, i)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, value, idPrefix = 'tab', children }) {
  if (id !== value) return null;
  return <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-${id}`} tabIndex={0}>{children}</div>;
}
