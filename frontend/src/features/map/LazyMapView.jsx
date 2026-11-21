import { lazy, Suspense } from 'react';

// The map (and the MapLibre engine behind it) is a separate chunk: downloaded only when a page actually renders a map.
const MapView = lazy(() => import('./MapView.jsx'));

export default function LazyMapView(props) {
  return (
    <Suspense fallback={<div className="map-placeholder" role="status" style={{ minHeight: 280, display: 'grid', placeItems: 'center' }}>Loading map…</div>}>
      <MapView {...props} />
    </Suspense>
  );
}
