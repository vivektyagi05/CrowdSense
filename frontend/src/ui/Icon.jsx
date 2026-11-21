// Small inline icon set (stroke icons, 20px grid). Decorative by default; pass `label` to expose one to screen readers.
const PATHS = {
  swap: 'M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7',
  search: 'm21 21-4.3-4.3M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z',
  close: 'M6 6l12 12M18 6 6 18',
  menu: 'M4 7h16M4 12h16M4 17h16',
  bus: 'M5 16V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v10M5 16h14M5 16v2h3v-2M16 16v2h3v-2M5 11h14M8.5 13.5h.01M15.5 13.5h.01',
  pin: 'M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 1 1 13 0c0 5.4-6.5 11-6.5 11ZM12 12a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4Z',
  check: 'm5 12.5 4.5 4.5L19 7.5',
  alert: 'M12 8v5M12 16.5h.01M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  info: 'M12 11v5M12 8h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z',
  chevron: 'm9 6 6 6-6 6',
  clock: 'M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1',
  compare: 'M8 4v16M16 4v16M4 8h8M12 16h8',
  refresh: 'M20 11a8 8 0 0 0-14.3-4.5L4 9M4 4v5h5M4 13a8 8 0 0 0 14.3 4.5L20 15M20 20v-5h-5',
};

export default function Icon({ name, size = 20, label, className = '' }) {
  return (
    <svg
      className={`icon ${className}`.trim()} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
