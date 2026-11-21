import { useEffect } from 'react';

/** Sets document.title for the current page (screen readers announce it on navigation). */
export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · CrowdSense` : 'CrowdSense';
  }, [title]);
}
