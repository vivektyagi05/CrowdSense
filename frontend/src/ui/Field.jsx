import { useId } from 'react';

/** Label + control + hint/error wiring shared by every form control, so labelling and aria-describedby are never forgotten. */
export function Field({ label, hint, error, children, className = '', htmlFor }) {
  return (
    <div className={`field ${error ? 'field--invalid' : ''} ${className}`.trim()}>
      <label className="field__label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <p className="field__hint" id={`${htmlFor}-hint`}>{hint}</p>}
      {error && <p className="field__error" id={`${htmlFor}-error`} role="alert">{error}</p>}
    </div>
  );
}

function describedBy(id, hint, error) {
  if (error) return `${id}-error`;
  return hint ? `${id}-hint` : undefined;
}

export function Input({ label, hint, error, className, ...props }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} htmlFor={id} className={className}>
      <input id={id} className="control" aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...props} />
    </Field>
  );
}

/** options: [{value, label}] */
export function Select({ label, hint, error, options, className, ...props }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} htmlFor={id} className={className}>
      <select id={id} className="control control--select" aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...props}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Field>
  );
}

/** Date + time selector producing one "YYYY-MM-DDTHH:MM" value (the format of the URL and the API). */
export function DateTimeField({ label, value, onChange, error, onNow }) {
  const id = useId();
  const [date = '', time = ''] = (value ?? '').split('T');
  const emit = (d, t) => onChange(d || t ? `${d}T${t}` : '');
  return (
    <fieldset className={`field datetime ${error ? 'field--invalid' : ''}`} aria-describedby={error ? `${id}-error` : undefined}>
      <legend className="field__label">{label}</legend>
      <div className="datetime__row">
        <input type="date" className="control" aria-label={`${label}: date`} aria-invalid={error ? true : undefined} value={date} onChange={(e) => emit(e.target.value, time)} required />
        <input type="time" className="control" aria-label={`${label}: time`} aria-invalid={error ? true : undefined} value={time} onChange={(e) => emit(date, e.target.value)} required />
        {onNow && <button type="button" className="btn btn--secondary btn--sm" onClick={onNow}>Now</button>}
      </div>
      {error && <p className="field__error" id={`${id}-error`} role="alert">{error}</p>}
    </fieldset>
  );
}
