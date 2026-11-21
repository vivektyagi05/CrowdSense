import { describeCrowd } from '../../lib/crowd.js';
import Icon from '../../ui/Icon.jsx';

/** The one place crowd state is rendered. Compact for cards, full for details. */
export default function CrowdStatus({ crowd, variant = 'compact' }) {
  const c = describeCrowd(crowd);
  return (
    <div className={`crowd-status crowd-status--${variant}`}>
      <Icon name="info" size={16} />
      <div>
        <strong>{c.title}</strong>
        {variant === 'full' ? <p>{c.detail} Crowd levels will appear here once verified passenger data is connected. Until then, nothing on this page implies how full a bus is.</p> : <span> {c.detail}</span>}
      </div>
    </div>
  );
}
