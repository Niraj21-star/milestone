import React, { useEffect, useRef } from 'react';
import { MapPin, Fuel, Coffee, BedDouble, ArrowRight } from 'lucide-react';

export default function StopTimeline({ stops, selectedStopId, onSelectStop }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (selectedStopId && containerRef.current) {
      const el = containerRef.current.querySelector(`[data-stop-id="${selectedStopId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  }, [selectedStopId]);

  if (!stops || stops.length === 0) return null;

  const getIcon = (type) => {
    switch (type) {
      case 'ORIGIN': return ArrowRight;
      case 'DESTINATION': return MapPin;
      case 'FUEL': return Fuel;
      case 'REST': return BedDouble;
      case 'BREAK': return Coffee;
      default: return MapPin;
    }
  };

  return (
    <div 
      className="card flex-col" 
      style={{ height: '600px', overflowY: 'auto', padding: 'var(--spacing-4)' }}
      ref={containerRef}
    >
      <h3 style={{ margin: '0 0 var(--spacing-4) 0', color: 'var(--color-primary)' }}>Trip Timeline</h3>
      
      <div style={{ display: 'flex', flexDirection: 'column', position: 'relative' }}>
        {/* Vertical line connector */}
        <div style={{
          position: 'absolute',
          left: '23px',
          top: '30px',
          bottom: '30px',
          width: '2px',
          backgroundColor: 'var(--color-border)',
          zIndex: 0
        }} />

        {stops.map((stop) => {
          const isSelected = stop.id === selectedStopId;
          const IconComponent = getIcon(stop.map_marker_type);
          
          return (
            <div 
              key={stop.id}
              data-stop-id={stop.id}
              onClick={() => onSelectStop(stop.id)}
              style={{
                display: 'flex',
                gap: 'var(--spacing-4)',
                padding: 'var(--spacing-3)',
                borderRadius: 'var(--radius-md)',
                backgroundColor: isSelected ? 'var(--color-bg)' : 'transparent',
                cursor: 'pointer',
                position: 'relative',
                zIndex: 1,
                transition: 'background-color 0.2s',
                marginBottom: 'var(--spacing-2)'
              }}
            >
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'var(--color-surface)',
                border: `2px solid ${isSelected ? 'var(--color-primary)' : 'var(--color-border)'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                color: isSelected ? 'var(--color-primary)' : 'var(--color-text-muted)',
                transition: 'border-color 0.2s'
              }}>
                <IconComponent size={20} />
              </div>
              
              <div style={{ flexGrow: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <span style={{ 
                      display: 'inline-block',
                      backgroundColor: 'var(--color-primary)',
                      color: '#ffffff',
                      fontSize: '11px',
                      fontWeight: 700,
                      padding: '2px 6px',
                      borderRadius: 'var(--radius-sm)',
                      marginRight: 'var(--spacing-2)',
                      letterSpacing: '0.5px'
                    }}>
                      DAY {stop.day_index + 1} · {new Date(stop.start_time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', hour12: false})}
                    </span>
                    <strong style={{ fontSize: 'var(--font-size-base)', color: 'var(--color-primary)' }}>
                      {stop.map_marker_type}
                    </strong>
                  </div>
                  <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)', fontWeight: 500 }}>
                    {stop.mileage_start.toFixed(1)} mi
                  </div>
                </div>
                
                <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-muted)', marginTop: '4px' }}>
                  {stop.location?.label || 'Route location'}
                  {stop.duration_minutes > 0 && ` · ${stop.duration_minutes} min duration`}
                </div>
                
                <div style={{ marginTop: 'var(--spacing-2)', fontSize: 'var(--font-size-sm)', color: 'var(--color-text)', lineHeight: 1.4 }}>
                  {stop.explanation}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
