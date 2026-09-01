import React from 'react';
import { CheckCircle, AlertTriangle, XCircle } from 'lucide-react';

export default function ComplianceBanner({ compliance }) {
  if (!compliance) return null;

  const status = compliance.status || (compliance.is_compliant === false ? 'BLOCKED' : compliance.warning ? 'WARNING' : 'COMPLIANT');
  const isBlocked = status === 'BLOCKED' || compliance.is_compliant === false;
  const isWarning = status === 'WARNING' || (compliance.is_compliant && compliance.warning);

  let color = 'var(--color-compliant)';
  let bg = '#ecfdf5'; // light green
  let Icon = CheckCircle;
  let title = 'COMPLIANT';
  let message = compliance.message || 'Compliant under modeled HOS assumptions.';

  if (isBlocked) {
    color = 'var(--color-blocked)';
    bg = '#fef2f2'; // light red
    Icon = XCircle;
    title = 'TRIP BLOCKED';
    message = compliance.message || compliance.warning || 'Trip cannot be completed under current HOS rules.';
  } else if (isWarning) {
    color = 'var(--color-accent)';
    bg = '#fffbeb'; // light amber
    Icon = AlertTriangle;
    title = 'WARNING';
    message = compliance.message || compliance.warning || 'Warning: approaching HOS cycle limits.';
  }

  return (
    <div 
      className="card flex-col gap-2" 
      style={{ 
        borderColor: color, 
        backgroundColor: bg,
        padding: 'var(--spacing-4)',
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 'var(--spacing-3)'
      }}
    >
      <Icon color={color} size={24} />
      <div>
        <h3 style={{ color, margin: 0, fontSize: 'var(--font-size-base)' }}>{title}</h3>
        <p style={{ color: 'var(--color-text)', margin: 0, fontSize: 'var(--font-size-sm)' }}>
          {message}
        </p>
      </div>
    </div>
  );
}
