import React, { useState } from 'react';
import EldDaySheet from './EldDaySheet';

export default function EldLogViewer({ dailyLogs }) {
  const [selectedDayIndex, setSelectedDayIndex] = useState(0);

  if (!dailyLogs || dailyLogs.length === 0) {
    return (
      <div className="card" style={{ padding: 'var(--spacing-4)' }}>
        <h3 style={{ margin: '0 0 var(--spacing-2) 0' }}>ELD Logs</h3>
        <p className="text-muted" style={{ margin: 0 }}>No daily logs available for this trip.</p>
      </div>
    );
  }

  const selectedLog = dailyLogs[selectedDayIndex] || dailyLogs[0];

  return (
    <div className="card" style={{ padding: 'var(--spacing-4)', display: 'flex', flexDirection: 'column', gap: 'var(--spacing-4)' }}>
      
      {/* Header and Tabs */}
      <div>
        <h3 style={{ margin: '0 0 var(--spacing-4) 0', color: 'var(--color-primary)' }}>ELD Driver Logs</h3>
        
        <div style={{ display: 'flex', gap: 'var(--spacing-2)', borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--spacing-2)', overflowX: 'auto' }} role="tablist">
          {dailyLogs.map((log, index) => {
            const isSelected = index === selectedDayIndex;
            return (
              <button
                key={log.day_index}
                onClick={() => setSelectedDayIndex(index)}
                role="tab"
                aria-selected={isSelected}
                id={`tab-day-${index}`}
                aria-controls={`panel-day-${index}`}
                style={{
                  padding: 'var(--spacing-2) var(--spacing-4)',
                  backgroundColor: isSelected ? 'var(--color-bg)' : 'transparent',
                  color: isSelected ? 'var(--color-primary)' : 'var(--color-text-muted)',
                  border: 'none',
                  borderBottom: isSelected ? '2px solid var(--color-primary)' : '2px solid transparent',
                  borderRadius: 'var(--radius-sm) var(--radius-sm) 0 0',
                  cursor: 'pointer',
                  fontWeight: isSelected ? 600 : 400,
                  fontSize: 'var(--font-size-base)',
                  transition: 'all 0.2s'
                }}
              >
                Day {index + 1}
              </button>
            );
          })}
        </div>
      </div>

      {/* Selected Day Content */}
      <div 
        role="tabpanel" 
        id={`panel-day-${selectedDayIndex}`} 
        aria-labelledby={`tab-day-${selectedDayIndex}`}
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-3)' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <span className="text-muted" style={{ fontSize: 'var(--font-size-sm)', textTransform: 'uppercase' }}>Date</span>
            <div style={{ fontWeight: 600 }}>{new Date(selectedLog.date).toLocaleDateString()}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span className="text-muted" style={{ fontSize: 'var(--font-size-sm)', textTransform: 'uppercase' }}>Miles Today</span>
            <div style={{ fontWeight: 600 }}>{selectedLog.total_miles?.toFixed(1)} mi</div>
          </div>
        </div>

        <EldDaySheet dayLog={selectedLog} />
      </div>

    </div>
  );
}
