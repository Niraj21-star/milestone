import React, { useState } from 'react';
import StatsHeaderStrip from './StatsHeaderStrip';
import ComplianceBanner from './ComplianceBanner';
import NextActionCard from './NextActionCard';
import RouteMap from './RouteMap';
import StopTimeline from './StopTimeline';
import EldLogViewer from './EldLogViewer';

export default function ResultsDashboard({ tripData }) {
  const [selectedStopId, setSelectedStopId] = useState(null);

  if (!tripData) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-5)', width: '100%' }} data-testid="results-dashboard">
      {/* Top Section: Overview Stats, Compliance Banner & Next Action */}
      <StatsHeaderStrip summary={tripData.summary} stops={tripData.stops} />
      <ComplianceBanner compliance={tripData.compliance} />
      
      {tripData.compliance?.is_compliant && (
        <NextActionCard stops={tripData.stops} />
      )}
      
      {/* Middle Section: Integrated Map (65%) & Stop Timeline (35%) Workspace */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'minmax(0, 1.8fr) minmax(0, 1fr)', 
        gap: 'var(--spacing-5)',
        alignItems: 'start'
      }} className="dashboard-grid">
        <RouteMap 
          route={tripData.route} 
          stops={tripData.stops} 
          selectedStopId={selectedStopId} 
        />
        <StopTimeline 
          stops={tripData.stops} 
          selectedStopId={selectedStopId} 
          onSelectStop={setSelectedStopId} 
        />
      </div>

      {/* Bottom Section: ELD Driver Logs Visualization */}
      <EldLogViewer dailyLogs={tripData.daily_logs} />

      <style>{`
        @media (max-width: 900px) {
          .dashboard-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
