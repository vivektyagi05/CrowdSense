/** One labelled number from the backend. */
export default function Stat({ label, value, note }) {
  return (
    <div className="stat">
      <dt className="stat__label">{label}</dt>
      <dd className="stat__value tnum">{value}</dd>
      {note && <dd className="stat__note">{note}</dd>}
    </div>
  );
}
