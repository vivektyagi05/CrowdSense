import { Link } from 'react-router-dom';
import { formatDuration } from '../../lib/time.js';
import { RouteBadge } from '../../ui/Badges.jsx';

/**
 * Vertical transit-diagram timeline: Origin → Board → intermediate stops → Alight → (Transfer → Board …) → Destination.
 * `legs[i]`: {routeId, routeName, tripId, headsign, durationMinutes, stops: [{id, name, time, dayOffset}]} where stops
 * runs from the boarding stop to the alighting stop inclusive. `waits[i]` is the wait between leg i and i+1.
 */
export default function JourneyTimeline({ legs, waits = [], activeStopId = null, onActiveStop }) {
  return (
    <ol className="timeline" aria-label="Journey timeline">
      {legs.map((leg, i) => {
        const board = leg.stops[0];
        const alight = leg.stops[leg.stops.length - 1];
        const middle = leg.stops.slice(1, -1);
        return (
          <li key={`${leg.tripId}-${i}`} className="timeline__leg">
            <div className="timeline__ride">
              <div className="timeline__ride-head">
                <RouteBadge id={leg.routeId} name={leg.routeName} />
                <div>
                  <p><strong>Board bus {leg.routeName}</strong>{leg.headsign ? <> towards {leg.headsign}</> : null}</p>
                  <p className="muted tnum">Trip {leg.tripId} · {formatDuration(leg.durationMinutes)} on board · {middle.length} stop{middle.length === 1 ? '' : 's'} between</p>
                </div>
              </div>
              <Stop kind="board" label={i === 0 ? 'Origin · board' : 'Board'} stop={board} activeStopId={activeStopId} onActiveStop={onActiveStop} />
              {middle.length > 0 && (
                <details className="timeline__middle">
                  <summary>{middle.length} intermediate stop{middle.length === 1 ? '' : 's'}</summary>
                  <ol>
                    {middle.map((s) => <Stop key={`${s.id}-${s.sequence}`} kind="mid" stop={s} activeStopId={activeStopId} onActiveStop={onActiveStop} />)}
                  </ol>
                </details>
              )}
              <Stop kind="alight" label={i === legs.length - 1 ? 'Alight · destination' : 'Alight'} stop={alight} activeStopId={activeStopId} onActiveStop={onActiveStop} />
            </div>
            {i < legs.length - 1 ? (
              <div className="timeline__transfer">
                <strong>Transfer at <Link to={`/stops/${encodeURIComponent(alight.id)}`}>{alight.name}</Link></strong>
                <p className="muted tnum">Scheduled wait {formatDuration(waits[i])}. Walking between stops is not modelled.</p>
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function Stop({ kind, label, stop, activeStopId, onActiveStop }) {
  const Tag = kind === 'mid' ? 'li' : 'div';
  const active = activeStopId != null && activeStopId === stop.id;
  const on = onActiveStop ? { onMouseEnter: () => onActiveStop(stop.id), onMouseLeave: () => onActiveStop(null), onFocus: () => onActiveStop(stop.id), onBlur: () => onActiveStop(null) } : {};
  return (
    <Tag className={`tl-stop tl-stop--${kind}${active ? ' tl-stop--active' : ''}`} data-stop-id={stop.id} {...on}>
      <span className="tl-stop__time tnum">{stop.time}{stop.dayOffset ? <sup title={`${stop.dayOffset} day after the service date`}>+{stop.dayOffset}</sup> : null}</span>
      <span className="tl-stop__dot" aria-hidden="true" />
      <span className="tl-stop__name">
        {label && <span className="tl-stop__label">{label}</span>}
        <Link to={`/stops/${encodeURIComponent(stop.id)}`}>{stop.name}</Link>
      </span>
    </Tag>
  );
}
