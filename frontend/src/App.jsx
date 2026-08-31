import React, { useState } from 'react';
import PlannerForm from './components/PlannerForm';
import { EmptyState, LoadingState, ErrorState } from './components/States';
import ResultsDashboard from './components/ResultsDashboard';
import { Compass, Radio } from 'lucide-react';

export default function App() {
  const [appState, setAppState] = useState('EMPTY'); // EMPTY, LOADING, ERROR, SUCCESS
  const [loadingMessage, setLoadingMessage] = useState('');
  const [errors, setErrors] = useState(null);
  const [tripData, setTripData] = useState(null);

  const handlePlanTrip = async (payload) => {
    setAppState('LOADING');
    setErrors(null);
    setTripData(null);
    setLoadingMessage('Geocoding locations…');

    const t1 = setTimeout(() => {
      setLoadingMessage('Calculating route…');
    }, 1200);

    const t2 = setTimeout(() => {
      setLoadingMessage('Building HOS schedule…');
    }, 2400);

    const t3 = setTimeout(() => {
      setLoadingMessage('Preparing driver logs…');
    }, 3600);

    try {
      const apiBase = import.meta.env.VITE_API_BASE_URL || '';
      const apiUrl = `${apiBase.replace(/\/$/, '')}/api/plan-trip/`;
      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);

      if (!response.ok) {
        throw new Error(`Server returned status ${response.status}`);
      }

      const data = await response.json();

      if (data.errors && data.errors.length > 0) {
        setErrors(data.errors);
        setAppState('ERROR');
      } else {
        setTripData(data);
        setAppState('SUCCESS');
      }
    } catch (err) {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      setErrors([{ code: 'NETWORK_ERROR', message: err.message }]);
      setAppState('ERROR');
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Global Application Header */}
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--spacing-2)' }}>
          <div className="brand-title">
            <Compass size={22} style={{ verticalAlign: 'middle', color: 'var(--color-accent)' }} />
            Milepost
          </div>
          <span className="brand-tagline">Plan the route. Know every stop.</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-4)' }}>
          <span style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--color-primary)' }}>
            Trip Planner
          </span>
          <div className="header-badge">
            <span className="badge-dot"></span>
            System Ready
          </div>
        </div>
      </header>

      {/* Main Operational Workspace Layout */}
      <main className="app-container">
        <div className="workspace-grid">
          {/* Left Column: Trip Planner Input Sidebar */}
          <aside>
            <PlannerForm onSubmit={handlePlanTrip} disabled={appState === 'LOADING'} />
          </aside>

          {/* Right Column: Dashboard Display Workspace */}
          <section>
            {appState === 'EMPTY' && <EmptyState />}
            {appState === 'LOADING' && <LoadingState message={loadingMessage} />}
            {appState === 'ERROR' && <ErrorState errors={errors} />}
            {appState === 'SUCCESS' && tripData && (
              <ResultsDashboard tripData={tripData} />
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
