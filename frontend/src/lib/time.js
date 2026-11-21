// Time handling. The feed is Delhi static GTFS (agency timezone Asia/Kolkata): every API time is a *local feed time*
// without a UTC offset, so it is formatted by slicing the string, never by `new Date(...)` (which would apply the
// browser's timezone). "Now" is always computed in the feed timezone, whatever the browser's timezone is.

export const FEED_TIMEZONE = 'Asia/Kolkata';

const nowParts = new Intl.DateTimeFormat('en-GB', {
  timeZone: FEED_TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

/** Current date (YYYY-MM-DD) and time (HH:MM) in Delhi. */
export function delhiNow(now = new Date()) {
  const p = Object.fromEntries(nowParts.formatToParts(now).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
}

/** Default search moment: right now in Delhi (minute precision), for <input type="datetime-local">-style values. */
export function defaultDeparture(now = new Date()) {
  const { date, time } = delhiNow(now);
  return `${date}T${time}`;
}

const DEPARTURE_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/** Validate a local departure string. Returns {ok, value, date, time} or {ok:false, reason}. */
export function parseDeparture(value) {
  const m = DEPARTURE_RE.exec(value ?? '');
  if (!m) return { ok: false, reason: 'Enter a valid date and time.' };
  const [, y, mo, d, h, mi] = m.map(Number);
  const probe = new Date(Date.UTC(y, mo - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) {
    return { ok: false, reason: 'That date does not exist.' };
  }
  if (h > 23 || mi > 59) return { ok: false, reason: 'That time does not exist.' };
  const date = `${m[1]}-${m[2]}-${m[3]}`;
  const time = `${m[4]}:${m[5]}`;
  return { ok: true, value: `${date}T${time}`, date, time };
}

export function addDays(date, days) {
  const [y, m, d] = date.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return t.toISOString().slice(0, 10);
}

/** "HH:MM" from a local ISO datetime string. */
export function clockOf(iso) {
  return iso ? iso.slice(11, 16) : '';
}

/** Whole days between two local ISO datetimes' dates (later - earlier). */
export function dayDelta(fromDate, iso) {
  if (!iso) return 0;
  const a = Date.parse(`${fromDate}T00:00:00Z`);
  const b = Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

/** Minutes between two local ISO datetimes (both in the same timezone, so plain UTC arithmetic is exact). */
export function minutesBetween(startIso, endIso) {
  return Math.round((Date.parse(`${endIso}Z`) - Date.parse(`${startIso}Z`)) / 60_000);
}

/** GTFS "HH:MM:SS" (hours may be >= 24) -> {clock:'HH:MM', dayOffset, seconds}. */
export function parseGtfsTime(value) {
  const m = /^(\d{1,3}):(\d{2}):(\d{2})$/.exec(value ?? '');
  if (!m) return null;
  const hours = Number(m[1]);
  return { clock: `${String(hours % 24).padStart(2, '0')}:${m[2]}`, dayOffset: Math.floor(hours / 24), seconds: hours * 3600 + Number(m[2]) * 60 + Number(m[3]) };
}

export function formatDuration(minutes) {
  if (minutes == null || Number.isNaN(minutes)) return '';
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function formatDateLong(date) {
  const [y, m, d] = date.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', {
    timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
  });
}

/** GTFS YYYYMMDD -> "1 Jan 2025". */
export function formatGtfsDate(value) {
  if (!/^\d{8}$/.test(value ?? '')) return value ?? '';
  return formatDateLong(`${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`);
}

export function formatNumber(n) {
  return n == null ? '' : new Intl.NumberFormat('en-IN').format(n);
}
