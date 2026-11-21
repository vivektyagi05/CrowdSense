import { Link } from 'react-router-dom';
import { clockOf, dayDelta, formatDuration } from '../../lib/time.js';
import { journeyDetailPath } from '../../lib/journeys.js';
import { RouteBadge, StatusBadge } from '../../ui/Badges.jsx';
import Icon from '../../ui/Icon.jsx';
import CrowdStatus from './CrowdStatus.jsx';

export default function JourneyCard({ journey, search, compared, onToggleCompare, compareDisabled }) {
  const next = dayDelta(search.date, journey.arrival);
  const first = journey.legs[0];
  return (
    <article className="journey-card" aria-label={`Journey departing ${clockOf(journey.departure)}`}>
      <div className="journey-card__times">
        <p className="journey-card__clock tnum">
          <time dateTime={journey.departure}>{clockOf(journey.departure)}</time>
          <Icon name="chevron" size={16} />
          <time dateTime={journey.arrival}>{clockOf(journey.arrival)}</time>
          {next > 0 && <span className="journey-card__next-day">+{next} day</span>}
        </p>
        <p className="journey-card__duration tnum">{formatDuration(journey.durationMinutes)}</p>
      </div>
      <div className="journey-card__body">
        <ul className="journey-card__legs">
          {journey.legs.map((leg) => (
            <li key={`${leg.tripId}-${leg.departure}`}>
              <RouteBadge id={leg.routeId} name={leg.routeName} />
              <span className="journey-card__path">{leg.from.name} <span aria-hidden="true">→</span><span className="sr-only"> to </span> {leg.to.name}</span>
            </li>
          ))}
        </ul>
        <p className="journey-card__facts">
          <StatusBadge tone="success">{journey.transfers === 0 ? 'Direct' : `${journey.transfers} transfer${journey.transfers === 1 ? '' : 's'}`}</StatusBadge>
          <span className="tnum">{first.intermediateStops} stop{first.intermediateStops === 1 ? '' : 's'} between</span>
          {journey.waitingMinutes > 0 && <span className="tnum">{formatDuration(journey.waitingMinutes)} waiting</span>}
          <span>Scheduled</span>
        </p>
        <CrowdStatus crowd={journey.crowd} />
      </div>
      <div className="journey-card__actions">
        <Link className="btn btn--primary btn--sm" to={journeyDetailPath(journey, search)} state={{ fromResults: true }}>View journey</Link>
        <label className="check">
          <input type="checkbox" checked={compared} disabled={compareDisabled && !compared} onChange={() => onToggleCompare(journey.id)} />
          <span>Compare</span>
        </label>
      </div>
    </article>
  );
}
