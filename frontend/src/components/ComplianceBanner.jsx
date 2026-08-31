import React from 'react';
import { CheckCircle, AlertTriangle, XCircle } from 'lucide-react';

export default function ComplianceBanner({ compliance }) {
  if (!compliance) return null;

  const { is_compliant, warning } = compliance;

  let color = 'var(--color-compliant)';
  let bg = '#ecfdf5'; // light green
  let Icon = CheckCircle;
  let title = 'COMPLIANT';
  let message = 'Compliant under modeled HOS assumptions.';

  if (!is_compliant) {
    color = 'var(--color-blocked)';
    bg = '#fef2f2'; // light red
    Icon = XCircle;
    title = 'TRIP BLOCKED';
    message = warning || 'Trip cannot be completed under current HOS rules.';
  } else if (warning) {
    color = 'var(--color-accent)';
    bg = '#fffbeb'; // light amber
    Icon = AlertTriangle;
    title = 'WARNING';
    message = warning;
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
