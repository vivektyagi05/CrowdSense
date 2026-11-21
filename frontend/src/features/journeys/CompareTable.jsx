import { Link } from 'react-router-dom';
import { clockOf, formatDuration } from '../../lib/time.js';
import { journeyDetailPath } from '../../lib/journeys.js';
import { RouteBadge } from '../../ui/Badges.jsx';

/** Side-by-side comparison of up to three journeys. Best value in each numeric row is marked. */
export default function CompareTable({ journeys, search }) {
  const best = (key, pick = Math.min) => pick(...journeys.map((j) => j[key]));
  const rows = [
    { label: 'Departs', value: (j) => clockOf(j.departure) },
    { label: 'Arrives', value: (j) => clockOf(j.arrival) },
    { label: 'Duration', value: (j) => formatDuration(j.durationMinutes), best: (j) => j.durationMinutes === best('durationMinutes') },
    { label: 'Transfers', value: (j) => (j.transfers === 0 ? 'Direct' : j.transfers), best: (j) => j.transfers === best('transfers') },
    { label: 'Waiting', value: (j) => formatDuration(j.waitingMinutes) || '0 min', best: (j) => j.waitingMinutes === best('waitingMinutes') },
    { label: 'Stops between', value: (j) => j.stopsBetween },
    { label: 'Crowd', value: () => 'Data unavailable' },
  ];
  return (
    <div className="table-scroll">
      <table className="compare">
        <caption className="sr-only">Comparison of selected journeys</caption>
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">Measure</span></th>
            {journeys.map((j) => (
              <th scope="col" key={j.id}>{j.legs.map((l) => <RouteBadge key={l.tripId} id={l.routeId} name={l.routeName} to={null} />)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {journeys.map((j) => (
                <td key={j.id} className={`tnum ${row.best && journeys.length > 1 && row.best(j) ? 'is-best' : ''}`}>{row.value(j)}{row.best && journeys.length > 1 && row.best(j) ? <span className="sr-only"> (best)</span> : null}</td>
              ))}
            </tr>
          ))}
          <tr>
            <th scope="row">Details</th>
            {journeys.map((j) => <td key={j.id}><Link to={journeyDetailPath(j, search)}>Open journey</Link></td>)}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
