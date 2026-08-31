import React from 'react';
import { ArrowRight, MapPin, Fuel, BedDouble, Shield, Compass } from 'lucide-react';

export default function StatsHeaderStrip({ summary, stops }) {
  if (!summary) return null;

  // Extract origin, pickup, dropoff labels from stops if available
  const originStop = stops?.find(s => s.map_marker_type === 'ORIGIN');
  const pickupStop = stops?.find(s => s.map_marker_type === 'PICKUP');
  const dropoffStop = stops?.find(s => s.map_marker_type === 'DROPOFF');

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-4)' }}>
      {/* Route Overview Bar */}
      {(originStop || pickupStop || dropoffStop) && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--spacing-3)',
          paddingBottom: 'var(--spacing-3)',
          borderBottom: '1px solid var(--color-border)',
          overflowX: 'auto'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-2)', whiteSpace: 'nowrap' }}>
            <span className="form-label" style={{ color: 'var(--color-text-muted)' }}>CURRENT</span>
            <strong style={{ fontSize: 'var(--font-size-base)', color: 'var(--color-primary)' }}>
              {originStop?.location?.label || 'Current Location'}
            </strong>
          </div>
          <ArrowRight size={16} color="var(--color-text-muted)" style={{ flexShrink: 0 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-2)', whiteSpace: 'nowrap' }}>
            <span className="form-label" style={{ color: 'var(--color-compliant)' }}>PICKUP</span>
            <strong style={{ fontSize: 'var(--font-size-base)', color: 'var(--color-primary)' }}>
              {pickupStop?.location?.label || 'Pickup Location'}
            </strong>
          </div>
          <ArrowRight size={16} color="var(--color-text-muted)" style={{ flexShrink: 0 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-2)', whiteSpace: 'nowrap' }}>
            <span className="form-label" style={{ color: 'var(--color-blocked)' }}>DROPOFF</span>
            <strong style={{ fontSize: 'var(--font-size-base)', color: 'var(--color-primary)' }}>
              {dropoffStop?.location?.label || 'Dropoff Location'}
            </strong>
          </div>
        </div>
      )}

      {/* Metrics Row */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', 
        gap: 'var(--spacing-3)' 
      }}>
        <div className="stat-item">
          <p className="form-label">DISTANCE</p>
          <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary)' }}>
            {summary.total_distance_miles.toLocaleString()} mi
          </p>
        </div>

        <div className="stat-item">
          <p className="form-label">DRIVING</p>
          <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary)' }}>
            {Math.floor(summary.total_driving_hours)}h {Math.round((summary.total_driving_hours % 1) * 60)}m
          </p>
        </div>

        <div className="stat-item">
          <p className="form-label">TRIP TIME</p>
          <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary)' }}>
            {summary.total_trip_days}d {Math.floor(summary.total_driving_hours)}h
          </p>
        </div>

        <div className="stat-item">
          <p className="form-label">CYCLE REMAINING</p>
          <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-accent)' }}>
            {summary.cycle_remaining_at_end_hours.toFixed(1)}h
          </p>
        </div>

        <div className="stat-item">
          <p className="form-label">FUEL STOPS</p>
          <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary)' }}>
            {summary.fuel_stop_count}
          </p>
        </div>

        <div className="stat-item">
          <p className="form-label">REST STOPS</p>
          <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary)' }}>
            {summary.rest_stop_count}
          </p>
        </div>
      </div>
    </div>
  );
}
