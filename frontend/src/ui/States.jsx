import Button from './Button.jsx';
import Icon from './Icon.jsx';

export function Skeleton({ lines = 3, label = 'Loading' }) {
  return (
    <div className="skeleton" role="status" aria-live="polite" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => <span key={i} className="skeleton__line" style={{ width: `${95 - ((i * 17) % 40)}%` }} />)}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state state--empty">
      <Icon name="info" size={28} />
      <h3>{title}</h3>
      {children && <div className="state__body">{children}</div>}
      {action}
    </div>
  );
}

/** Error with an optional retry. `error` is an ApiError (or anything with .message). */
export function ErrorState({ title = 'Something went wrong', error, onRetry }) {
  return (
    <div className="state state--error" role="alert">
      <Icon name="alert" size={28} />
      <h3>{title}</h3>
      <p className="state__body">{error?.message ?? 'Unexpected error.'}</p>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}><Icon name="refresh" size={16} />Retry</Button>}
    </div>
  );
}

/** Inline message. tone: info | warning | danger | success */
export function Notice({ tone = 'info', title, children }) {
  return (
    <div className={`notice notice--${tone}`} role={tone === 'danger' ? 'alert' : undefined}>
      <Icon name={tone === 'danger' || tone === 'warning' ? 'alert' : 'info'} size={18} />
      <div>{title && <strong className="notice__title">{title}</strong>}<div>{children}</div></div>
    </div>
  );
}
