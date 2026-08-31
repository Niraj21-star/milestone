import React, { useState } from 'react';
import { MapPin, Navigation, Flag, Clock, ArrowRight } from 'lucide-react';

export default function PlannerForm({ onSubmit, disabled }) {
  const [currentLocation, setCurrentLocation] = useState('');
  const [pickupLocation, setPickupLocation] = useState('');
  const [dropoffLocation, setDropoffLocation] = useState('');
  const [cycleUsed, setCycleUsed] = useState('0');
  const [validationError, setValidationError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    setValidationError('');

    const cycleVal = parseFloat(cycleUsed);
    if (isNaN(cycleVal) || cycleVal >= 70 || cycleVal < 0) {
      setValidationError('Current Cycle Used must be between 0 and 69.9 hours.');
      return;
    }

    if (!currentLocation.trim() || !pickupLocation.trim() || !dropoffLocation.trim()) {
      setValidationError('All location fields are required.');
      return;
    }

    onSubmit({
      current_location: currentLocation.trim(),
      pickup_location: pickupLocation.trim(),
      dropoff_location: dropoffLocation.trim(),
      current_cycle_used_hours: cycleVal,
    });
  };

  return (
    <div className="card">
      <div style={{ marginBottom: 'var(--spacing-4)', borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--spacing-3)' }}>
        <h2 style={{ fontSize: 'var(--font-size-base)', fontWeight: 700, color: 'var(--color-primary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          PLAN YOUR TRIP
        </h2>
        <p style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-muted)', marginTop: '2px' }}>
          Enter origin, pickup, dropoff & cycle status.
        </p>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-4)' }} data-testid="planner-form">
        <div className="form-group">
          <label htmlFor="currentLocation" className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Navigation size={12} color="var(--color-primary)" /> Current Location
          </label>
          <input
            id="currentLocation"
            type="text"
            value={currentLocation}
            onChange={(e) => setCurrentLocation(e.target.value)}
            disabled={disabled}
            placeholder="e.g. Chicago, IL"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="pickupLocation" className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <MapPin size={12} color="var(--color-compliant)" /> Pickup Location
          </label>
          <input
            id="pickupLocation"
            type="text"
            value={pickupLocation}
            onChange={(e) => setPickupLocation(e.target.value)}
            disabled={disabled}
            placeholder="e.g. Indianapolis, IN"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="dropoffLocation" className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Flag size={12} color="var(--color-blocked)" /> Dropoff Location
          </label>
          <input
            id="dropoffLocation"
            type="text"
            value={dropoffLocation}
            onChange={(e) => setDropoffLocation(e.target.value)}
            disabled={disabled}
            placeholder="e.g. Denver, CO"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="cycleUsed" className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Clock size={12} color="var(--color-accent)" /> Current Cycle Used (Hrs)
          </label>
          <input
            id="cycleUsed"
            type="number"
            step="0.1"
            min="0"
            max="69.9"
            value={cycleUsed}
            onChange={(e) => setCycleUsed(e.target.value)}
            disabled={disabled}
            required
          />
        </div>

        {validationError && (
          <div className="text-error" style={{ fontSize: 'var(--font-size-sm)', fontWeight: 500 }} data-testid="validation-error">
            {validationError}
          </div>
        )}

        <button type="submit" disabled={disabled} style={{ marginTop: 'var(--spacing-2)' }}>
          Plan Trip <ArrowRight size={16} />
        </button>
      </form>
    </div>
  );
}
