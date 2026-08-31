import React from 'react';
import { ArrowRight, Clock, MapPin, Fuel, Coffee, BedDouble } from 'lucide-react';

const formatTime = (isoString) => {
  if (!isoString) return '';
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
};

export default function NextActionCard({ stops }) {
  // Find the first non-origin/destination stop
  const nextAction = stops?.find(s => ['FUEL', 'BREAK_30M', 'RESET_10H', 'RESET_34H'].includes(s.reason));

  if (!nextAction) {
    return (
      <div className="card" style={{ padding: 'var(--spacing-4)', display: 'flex', alignItems: 'center', gap: 'var(--spacing-3)' }}>
        <div style={{ padding: 'var(--spacing-2)', backgroundColor: 'var(--color-bg)', borderRadius: 'var(--radius-md)' }}>
          <ArrowRight size={20} color="var(--color-text-muted)" />
        </div>
        <div>
          <h3 style={{ margin: 0, fontSize: 'var(--font-size-base)' }}>Next Action</h3>
          <p className="text-muted" style={{ margin: 0, fontSize: 'var(--font-size-sm)' }}>No additional stops required.</p>
        </div>
      </div>
    );
  }

  const getIcon = (reason) => {
    switch (reason) {
      case 'FUEL': return <Fuel size={20} color="var(--color-primary)" />;
      case 'BREAK_30M': return <Coffee size={20} color="var(--color-primary)" />;
      default: return <BedDouble size={20} color="var(--color-primary)" />;
    }
  };

  const getLabel = (reason) => {
    switch(reason) {
      case 'BREAK_30M': return 'REST';
      case 'RESET_10H': return 'REST';
      case 'RESET_34H': return 'REST';
      default: return reason;
    }
  };

  const minsToReadable = (mins) => {
    if (mins >= 60) {
      return `${Math.floor(mins/60)} hr`;
    }
    return `${mins} min`;
  }

  return (
    <div className="card" style={{ padding: 'var(--spacing-4)', display: 'flex', flexDirection: 'column', gap: 'var(--spacing-3)' }}>
      <h3 style={{ margin: 0, fontSize: 'var(--font-size-base)', color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>Next Required Action</h3>
      
      <div style={{ display: 'flex', gap: 'var(--spacing-4)', alignItems: 'flex-start' }}>
        <div style={{ padding: 'var(--spacing-2)', backgroundColor: 'var(--color-bg)', borderRadius: 'var(--radius-md)' }}>
          {getIcon(nextAction.reason)}
        </div>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-1)' }}>
          <div style={{ fontWeight: 600, fontSize: 'var(--font-size-lg)' }}>
            {getLabel(nextAction.reason)}
          </div>
          
          <div style={{ display: 'flex', gap: 'var(--spacing-3)', color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)', alignItems: 'center' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Clock size={14} /> {formatTime(nextAction.start_time)} · {minsToReadable(nextAction.duration_minutes)}
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <MapPin size={14} /> {nextAction.mileage_start.toFixed(1)} mi
            </span>
          </div>

          <div style={{ marginTop: 'var(--spacing-2)', fontSize: 'var(--font-size-sm)' }}>
            <strong>{nextAction.location?.label || 'Route location'}</strong>
            <p className="text-muted" style={{ margin: '4px 0 0 0' }}>{nextAction.explanation}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
