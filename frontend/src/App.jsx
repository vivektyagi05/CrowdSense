import { lazy, Suspense, useState } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import AppShell from './app/AppShell.jsx';
import { Skeleton } from './ui/States.jsx';

// Route-level code splitting: each page is its own chunk, loaded when first visited.
const HomePage = lazy(() => import('./pages/HomePage.jsx'));
const JourneysPage = lazy(() => import('./pages/JourneysPage.jsx'));
const JourneyDetailPage = lazy(() => import('./pages/JourneyDetailPage.jsx'));
const NearbyPage = lazy(() => import('./pages/NearbyPage.jsx'));
const ExplorePage = lazy(() => import('./pages/ExplorePage.jsx'));
const StopDetailPage = lazy(() => import('./pages/StopDetailPage.jsx'));
const RouteDetailPage = lazy(() => import('./pages/RouteDetailPage.jsx'));
const InsightsPage = lazy(() => import('./pages/InsightsPage.jsx'));
const AboutPage = lazy(() => import('./pages/AboutPage.jsx'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage.jsx'));

const page = (el) => <Suspense fallback={<div className="container page"><Skeleton lines={4} label="Loading page" /></div>}>{el}</Suspense>;

export const routes = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: page(<HomePage />) },
      { path: 'journeys', element: page(<JourneysPage />) },
      { path: 'journeys/:tripId', element: page(<JourneyDetailPage />) },
      { path: 'nearby', element: page(<NearbyPage />) },
      { path: 'explore', element: page(<ExplorePage />) },
      { path: 'stops/:stopId', element: page(<StopDetailPage />) },
      { path: 'routes/:routeId', element: page(<RouteDetailPage />) },
      { path: 'insights', element: page(<InsightsPage />) },
      { path: 'about', element: page(<AboutPage />) },
      { path: '*', element: page(<NotFoundPage />) },
    ],
  },
];

export const createAppRouter = () => createBrowserRouter(routes);

export default function App() {
  const [router] = useState(createAppRouter);
  return <RouterProvider router={router} />;
}
