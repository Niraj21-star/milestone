import React, { useState } from 'react';

const STATUS_Y = {
  'OFF_DUTY': 30,
  'SLEEPER_BERTH': 70,
  'DRIVING': 110,
  'ON_DUTY_NOT_DRIVING': 150
};

const formatDuration = (mins) => {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  return `${m}m`;
};

const formatTime = (dtString) => {
  if (!dtString) return '';
  return new Date(dtString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

export default function EldDaySheet({ dayLog }) {
  const [hoveredEvent, setHoveredEvent] = useState(null);

  if (!dayLog || !dayLog.events) return null;

  return (
    <div className="eld-day-sheet" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-4)' }}>
      
      {/* ELD Main Grid (SVG) */}
      <div 
        style={{ 
          overflowX: 'auto', 
          backgroundColor: '#ffffff', 
          border: '1px solid var(--color-border)', 
          borderRadius: 'var(--radius-md)',
          padding: 'var(--spacing-4)',
          position: 'relative'
        }}
      >
        <div style={{ minWidth: '800px' }}>
          <svg viewBox="-150 0 1600 180" width="100%" height="100%" preserveAspectRatio="xMinYMid meet">
            
            {/* Grid Lines */}
            {/* Horizontal duty rows */}
            {Object.values(STATUS_Y).map((y, i) => (
              <line key={`hline-${i}`} x1={0} x2={1440} y1={y} y2={y} stroke="#f1f5f9" strokeWidth={1} />
            ))}

            {/* Vertical 15-min ticks */}
            {Array.from({ length: 24 * 4 + 1 }).map((_, i) => {
              if (i % 4 === 0) return null; // Skip hours
              return (
                <line key={`m-${i}`} x1={i * 15} x2={i * 15} y1={20} y2={160} stroke="#f1f5f9" strokeWidth={1} />
              );
            })}

            {/* Vertical Hour Lines */}
            {Array.from({ length: 25 }).map((_, i) => (
              <g key={`h-${i}`}>
                <line x1={i * 60} x2={i * 60} y1={20} y2={160} stroke="#cbd5e1" strokeWidth={1} />
                <text x={i * 60} y={15} fontSize={10} textAnchor="middle" fill="#64748b">
                  {i.toString().padStart(2, '0')}
                </text>
              </g>
            ))}

            {/* Row Labels */}
            <text x={-10} y={34} fontSize={12} textAnchor="end" fontWeight="600" fill="#1e293b">OFF DUTY</text>
            <text x={-10} y={74} fontSize={12} textAnchor="end" fontWeight="600" fill="#1e293b">SLEEPER BERTH</text>
            <text x={-10} y={114} fontSize={12} textAnchor="end" fontWeight="600" fill="#1e293b">DRIVING</text>
            <text x={-10} y={154} fontSize={12} textAnchor="end" fontWeight="600" fill="#1e293b">ON DUTY NOT DRIVING</text>

            {/* Event Rendering */}
            {dayLog.events.map((event, i) => {
              const y = STATUS_Y[event.status];
              const prevEvent = i > 0 ? dayLog.events[i - 1] : null;
              
              // Draw vertical transition if status changed
              let transition = null;
              if (prevEvent && prevEvent.status !== event.status && prevEvent.end_minute_of_day === event.start_minute_of_day) {
                transition = (
                  <line 
                    key={`trans-${i}`} 
                    x1={event.start_minute_of_day} 
                    x2={event.start_minute_of_day} 
                    y1={STATUS_Y[prevEvent.status]} 
                    y2={y} 
                    stroke="var(--color-primary)" 
                    strokeWidth={4} 
                  />
                );
              }

              // Event line segment
              // If it's a day_fill, we can style it slightly different or just normal
              const isRenderingOnly = event.is_rendering_only;
              const color = isRenderingOnly ? '#94a3b8' : 'var(--color-primary)';
              const strokeWidth = isRenderingOnly ? 2 : 4;

              return (
                <g key={`event-${event.origin_event_id}-${i}`}>
                  {transition}
                  <line 
                    x1={event.start_minute_of_day} 
                    x2={event.end_minute_of_day} 
                    y1={y} 
                    y2={y} 
                    stroke={color}
                    strokeWidth={strokeWidth}
                    strokeLinecap="round"
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={() => setHoveredEvent(event)}
                    onMouseLeave={() => setHoveredEvent(null)}
                    onFocus={() => setHoveredEvent(event)}
                    onBlur={() => setHoveredEvent(null)}
                    tabIndex={0}
                    role="graphics-symbol"
                    aria-label={`Duty status ${event.status} from minute ${event.start_minute_of_day} to ${event.end_minute_of_day}`}
                  />
                  {/* Invisible hit area for easier hovering over thin lines */}
                  <line 
                    x1={event.start_minute_of_day} 
                    x2={event.end_minute_of_day} 
                    y1={y} 
                    y2={y} 
                    stroke="transparent"
                    strokeWidth={16}
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={() => setHoveredEvent(event)}
                    onMouseLeave={() => setHoveredEvent(null)}
                  />
                </g>
              );
            })}
          </svg>
        </div>

        {/* Hover Popover */}
        {hoveredEvent && (
          <div 
            style={{ 
              position: 'absolute', 
              top: '10px', 
              right: '10px', 
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--spacing-3)',
              boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
              zIndex: 10,
              minWidth: '250px'
            }}
            data-testid="event-tooltip"
          >
            <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--color-primary)' }}>
              {hoveredEvent.status.replace(/_/g, ' ')}
            </div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-muted)' }}>
              {formatTime(hoveredEvent.start_time)} – {formatTime(hoveredEvent.end_time)} ({formatDuration(hoveredEvent.duration_minutes)})
            </div>
            {hoveredEvent.location?.label && (
              <div style={{ fontSize: 'var(--font-size-sm)', marginTop: '4px' }}>
                <strong>Location:</strong> {hoveredEvent.location.label}
              </div>
            )}
            <div style={{ fontSize: 'var(--font-size-sm)', marginTop: '4px' }}>
              <strong>Reason:</strong> {hoveredEvent.reason}
            </div>
            {hoveredEvent.explanation && (
              <div style={{ fontSize: 'var(--font-size-sm)', marginTop: '4px', color: 'var(--color-text-muted)' }}>
                {hoveredEvent.explanation}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--spacing-4)' }}>
        
        {/* Remarks */}
        <div className="card">
          <h4 style={{ margin: '0 0 var(--spacing-3) 0', color: 'var(--color-primary)' }}>Remarks</h4>
          {dayLog.remarks && dayLog.remarks.length > 0 ? (
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 'var(--spacing-2)' }}>
              {dayLog.remarks.map((rm, i) => (
                <li key={`rm-${i}`} style={{ display: 'flex', gap: 'var(--spacing-3)', fontSize: 'var(--font-size-sm)' }}>
                  <span style={{ fontWeight: 600, minWidth: '45px' }}>
                    {String(Math.floor(rm.minute_of_day / 60)).padStart(2, '0')}:{String(rm.minute_of_day % 60).padStart(2, '0')}
                  </span>
                  <span style={{ fontWeight: 600, color: 'var(--color-primary)', minWidth: '100px' }}>{rm.label}</span>
                  <span className="text-muted">{rm.location_label}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted" style={{ margin: 0, fontSize: 'var(--font-size-sm)' }}>No remarks for this day.</p>
          )}
        </div>

        {/* Totals */}
        <div className="card">
          <h4 style={{ margin: '0 0 var(--spacing-3) 0', color: 'var(--color-primary)' }}>Duty Totals</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-2)', fontSize: 'var(--font-size-sm)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="text-muted">Off Duty</span>
              <span style={{ fontWeight: 600 }}>{formatDuration(dayLog.totals_minutes?.OFF_DUTY ?? dayLog.totals_minutes?.off_duty ?? 0)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="text-muted">Sleeper Berth</span>
              <span style={{ fontWeight: 600 }}>{formatDuration(dayLog.totals_minutes?.SLEEPER_BERTH ?? dayLog.totals_minutes?.sleeper_berth ?? 0)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="text-muted">Driving</span>
              <span style={{ fontWeight: 600 }}>{formatDuration(dayLog.totals_minutes?.DRIVING ?? dayLog.totals_minutes?.driving ?? 0)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="text-muted">On Duty Not Driving</span>
              <span style={{ fontWeight: 600 }}>{formatDuration(dayLog.totals_minutes?.ON_DUTY_NOT_DRIVING ?? dayLog.totals_minutes?.on_duty_not_driving ?? 0)}</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
