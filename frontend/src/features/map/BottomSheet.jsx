import { useEffect, useId, useRef, useState } from 'react';
import './map.css';

function useIsPhone() {
  const q = '(max-width: 767px)';
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(q).matches);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const m = window.matchMedia(q); const on = () => setPhone(m.matches);
    m.addEventListener?.('change', on);
    return () => m.removeEventListener?.('change', on);
  }, []);
  return phone;
}

const ORDER = ['collapsed', 'half', 'full'];
const LABEL = { collapsed: 'Show details', half: 'Show more details', full: 'Hide details' };

/**
 * Details panel. Desktop/tablet: a normal block beside the map. Phones (CSS, < 768 px): a draggable bottom sheet.
 * The handle is a real button (Enter/Space cycles collapsed -> half -> full -> collapsed) and also responds to a
 * vertical drag. It is NOT modal: the map stays usable behind it and focus is never trapped.
 */
export default function BottomSheet({ title, children, className = '' }) {
  const [state, setState] = useState('half');
  const bodyId = useId();
  const drag = useRef(null);
  const phone = useIsPhone();

  const step = (dir) => setState((s) => ORDER[Math.min(ORDER.length - 1, Math.max(0, ORDER.indexOf(s) + dir))]);
  const cycle = () => setState((s) => ORDER[(ORDER.indexOf(s) + 1) % ORDER.length]);

  return (
    <div className={`map-layout__details sheet ${className}`} data-state={state}>
      <button
        type="button" className="sheet__handle" aria-expanded={state !== 'collapsed'} aria-controls={bodyId}
        onClick={() => { if (!drag.current?.moved) cycle(); drag.current = null; }}
        onPointerDown={(e) => { drag.current = { y: e.clientY, moved: false }; e.currentTarget.setPointerCapture?.(e.pointerId); }}
        onPointerMove={(e) => { if (drag.current && Math.abs(e.clientY - drag.current.y) > 12) drag.current.moved = true; }}
        onPointerUp={(e) => {
          const d = drag.current; if (!d) return;
          const dy = e.clientY - d.y;
          if (d.moved) { step(dy < 0 ? 1 : -1); }
        }}
      >
        <span>{title}</span><span aria-hidden="true" className="muted">{LABEL[state]}</span>
      </button>
      <div className="sheet__body" id={bodyId} inert={phone && state === 'collapsed'}>{children}</div>
    </div>
  );
}
