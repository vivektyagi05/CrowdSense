import Button from './Button.jsx';
import { formatNumber } from '../lib/time.js';

/** Offset pagination driven by the API's own total. Never renders page numbers it cannot back with data. */
export default function Pagination({ offset, limit, total, onChange, itemLabel = 'results' }) {
  if (!total) return null;
  const first = offset + 1;
  const last = Math.min(offset + limit, total);
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav className="pagination" aria-label="Pagination">
      <p className="pagination__summary tnum" aria-live="polite">
        {formatNumber(first)}–{formatNumber(last)} of {formatNumber(total)} {itemLabel}
        <span className="pagination__page"> · page {formatNumber(page)} of {formatNumber(pages)}</span>
      </p>
      <div className="pagination__buttons">
        <Button variant="secondary" size="sm" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</Button>
        <Button variant="secondary" size="sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</Button>
      </div>
    </nav>
  );
}
