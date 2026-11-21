import { useEffect, useRef } from 'react';
import Icon from './Icon.jsx';

/**
 * Modal built on the native <dialog>: focus is trapped, Escape closes, the page behind is inert and focus returns to
 * the opener. `variant="drawer"` slides it in from the right on wide screens and docks it to the bottom on phones.
 */
export default function Modal({ open, onClose, title, variant = 'dialog', children }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`modal modal--${variant}`} aria-labelledby="modal-title" onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {open && (
        <div className="modal__panel">
          <header className="modal__header">
            <h2 id="modal-title">{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
          </header>
          <div className="modal__body">{children}</div>
        </div>
      )}
    </dialog>
  );
}
