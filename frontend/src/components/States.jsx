import React from 'react';
import { Compass, AlertTriangle, Loader2 } from 'lucide-react';

export const EmptyState = () => (
  <div className="card text-center" style={{ padding: 'var(--spacing-10)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--spacing-3)' }} data-testid="empty-state">
    <Compass size={40} color="var(--color-text-muted)" style={{ opacity: 0.6 }} />
    <h3 style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary)' }}>
      PLAN YOUR NEXT TRIP
    </h3>
    <p className="text-muted" style={{ fontSize: 'var(--font-size-sm)', maxWidth: '420px', lineHeight: 1.5 }}>
      Enter your current location, pickup, dropoff, and cycle usage to generate a complete route plan.
    </p>
  </div>
);

export const LoadingState = ({ message }) => (
  <div className="card text-center" style={{ padding: 'var(--spacing-10)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--spacing-4)' }} data-testid="loading-state">
    <Loader2 size={36} color="var(--color-accent)" style={{ animation: 'spin 1.2s linear infinite' }} />
    <div>
      <h3 style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary)' }}>
        Generating Route Plan
      </h3>
      <p className="text-muted" style={{ fontSize: 'var(--font-size-sm)', marginTop: '4px' }}>
        {message || 'Processing trip parameters…'}
      </p>
    </div>
    <style>{`
      @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }
    `}</style>
  </div>
);

export const ErrorState = ({ errors }) => {
  return (
    <div className="card flex-col gap-3" style={{ borderColor: 'var(--color-blocked)', backgroundColor: 'var(--color-blocked-bg)', padding: 'var(--spacing-6)' }} data-testid="error-state">
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-3)' }}>
        <AlertTriangle color="var(--color-blocked)" size={24} />
        <h3 style={{ color: 'var(--color-blocked)', margin: 0, fontSize: 'var(--font-size-lg)' }}>
          Unable to plan trip
        </h3>
      </div>
      {errors && errors.length > 0 ? (
        <ul style={{ paddingLeft: '32px', color: 'var(--color-text)', fontSize: 'var(--font-size-sm)', display: 'flex', flexDirection: 'column', gap: 'var(--spacing-1)' }}>
          {errors.map((err, idx) => (
            <li key={idx}>
              <strong>{err.code}:</strong> {err.message}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-error" style={{ fontSize: 'var(--font-size-sm)' }}>
          An unexpected error occurred while planning the trip. Please check your inputs and try again.
        </p>
      )}
    </div>
  );
};
