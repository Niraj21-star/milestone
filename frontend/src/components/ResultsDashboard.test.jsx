import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import ResultsDashboard from './ResultsDashboard';

const mockTripData = {
  summary: {
    total_distance_miles: 1000.5,
    total_driving_hours: 15.2,
    total_trip_days: 2,
    cycle_remaining_at_end_hours: 50.1,
    fuel_stop_count: 1,
    rest_stop_count: 1,
  },
  compliance: {
    is_compliant: true,
    warning: null,
  },
  route: {
    legs: [
      { geometry: [{ lat: 10, lon: 10 }, { lat: 20, lon: 20 }] }
    ]
  },
  stops: [
    {
      id: 'stop-1',
      map_marker_type: 'ORIGIN',
      start_time: '2023-01-01T10:00:00Z',
      duration_minutes: 0,
      mileage_start: 0,
      explanation: 'Starting point',
      location: { label: 'Chicago, IL', lat: 10, lon: 10 }
    },
    {
      id: 'stop-2',
      reason: 'FUEL',
      map_marker_type: 'FUEL',
      start_time: '2023-01-01T14:00:00Z',
      duration_minutes: 30,
      mileage_start: 300,
      explanation: 'Refuel',
      location: { label: 'Gas Station', lat: 15, lon: 15 }
    }
  ]
};

const mockBlockedTripData = {
  ...mockTripData,
  compliance: {
    is_compliant: false,
    warning: 'Trip exceeds cycle limits',
  }
};

describe('ResultsDashboard', () => {
  it('renders StatsHeaderStrip with summary data', () => {
    render(<ResultsDashboard tripData={mockTripData} />);
    expect(screen.getByText(/1,000.5 mi/i)).toBeInTheDocument();
    expect(screen.getByText(/15h 12m/i)).toBeInTheDocument(); // 15.2 * 60 = 912 mins -> 15h 12m
    expect(screen.getByText(/50.1h/i)).toBeInTheDocument();
  });

  it('renders ComplianceBanner for compliant trip', () => {
    render(<ResultsDashboard tripData={mockTripData} />);
    expect(screen.getByText('COMPLIANT')).toBeInTheDocument();
    expect(screen.getByText('Compliant under modeled HOS assumptions.')).toBeInTheDocument();
  });

  it('renders ComplianceBanner for blocked trip', () => {
    render(<ResultsDashboard tripData={mockBlockedTripData} />);
    expect(screen.getByText('TRIP BLOCKED')).toBeInTheDocument();
    expect(screen.getByText('Trip exceeds cycle limits')).toBeInTheDocument();
  });

  it('renders NextActionCard with the first stop action', () => {
    render(<ResultsDashboard tripData={mockTripData} />);
    expect(screen.getByText('Next Required Action')).toBeInTheDocument();
    expect(screen.getAllByText('Refuel')[0]).toBeInTheDocument();
    expect(screen.getAllByText(/300.0 mi/i)[0]).toBeInTheDocument();
  });

  it('renders RouteMap and StopTimeline', () => {
    render(<ResultsDashboard tripData={mockTripData} />);
    expect(screen.getByTestId('map-container')).toBeInTheDocument();
    expect(screen.getByText('Trip Timeline')).toBeInTheDocument();
  });

  it('synchronizes selectedStopId from Timeline to Map', () => {
    const { container } = render(<ResultsDashboard tripData={mockTripData} />);
    const timelineItems = container.querySelectorAll('[data-stop-id]');
    expect(timelineItems.length).toBe(2);

    // Initial state: not selected
    expect(timelineItems[1]).toHaveStyle('background-color: rgba(0, 0, 0, 0)');

    // Click the second stop
    fireEvent.click(timelineItems[1]);

    // Check if state updated (background color changes based on selection)
    expect(timelineItems[1]).toHaveStyle('background-color: var(--color-bg)');
  });
});
