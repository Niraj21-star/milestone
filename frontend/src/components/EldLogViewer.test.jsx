import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import EldLogViewer from './EldLogViewer';

const mockDailyLogs = [
  {
    day_index: 0,
    date: '2023-01-01',
    total_miles: 450.5,
    totals_minutes: {
      OFF_DUTY: 600,
      SLEEPER_BERTH: 0,
      DRIVING: 540,
      ON_DUTY_NOT_DRIVING: 300,
    },
    remarks: [
      { minute_of_day: 60, label: 'Pickup', location_label: 'Chicago, IL', origin_event_id: 'e1' },
      { minute_of_day: 700, label: 'Fuel', location_label: 'Omaha, NE', origin_event_id: 'e2' }
    ],
    events: [
      {
        origin_event_id: 'day_fill',
        status: 'OFF_DUTY',
        start_minute_of_day: 0,
        end_minute_of_day: 60,
        duration_minutes: 60,
        is_rendering_only: true,
        reason: 'DAY_FILL',
        explanation: 'Off-duty (day fill)'
      },
      {
        origin_event_id: 'e1',
        status: 'ON_DUTY_NOT_DRIVING',
        start_minute_of_day: 60,
        end_minute_of_day: 120,
        duration_minutes: 60,
        is_rendering_only: false,
        reason: 'PICKUP',
        location: { label: 'Chicago, IL' },
        explanation: 'Loading freight'
      }
    ]
  },
  {
    day_index: 1,
    date: '2023-01-02',
    total_miles: 500,
    duty_totals: {
      OFF_DUTY: 840,
      SLEEPER_BERTH: 0,
      DRIVING: 600,
      ON_DUTY_NOT_DRIVING: 0,
    },
    remarks: [],
    events: [
      {
        origin_event_id: 'day_fill',
        status: 'OFF_DUTY',
        start_minute_of_day: 0,
        end_minute_of_day: 1440,
        duration_minutes: 1440,
        is_rendering_only: true,
        reason: 'DAY_FILL',
        explanation: 'Off-duty (day fill)'
      }
    ]
  }
];

describe('EldLogViewer', () => {
  it('renders gracefully when empty', () => {
    render(<EldLogViewer dailyLogs={[]} />);
    expect(screen.getByText('No daily logs available for this trip.')).toBeInTheDocument();
  });

  it('renders first day by default', () => {
    render(<EldLogViewer dailyLogs={mockDailyLogs} />);
    
    // Header check
    expect(screen.getByText(/450.5 mi/)).toBeInTheDocument();
    
    // Tab check
    const tab1 = screen.getByRole('tab', { name: 'Day 1' });
    expect(tab1).toHaveAttribute('aria-selected', 'true');
    
    // Row Labels
    expect(screen.getByText('OFF DUTY')).toBeInTheDocument();
    expect(screen.getByText('DRIVING')).toBeInTheDocument();
    
    // Remarks
    expect(screen.getByText('01:00')).toBeInTheDocument();
    expect(screen.getByText('Pickup')).toBeInTheDocument();
    expect(screen.getByText('Omaha, NE')).toBeInTheDocument();
    
    // Totals
    expect(screen.getByText('9h')).toBeInTheDocument(); // 540 mins Driving = 9h
    expect(screen.getByText('10h')).toBeInTheDocument(); // 600 mins Off Duty = 10h
  });

  it('switches tabs correctly', () => {
    render(<EldLogViewer dailyLogs={mockDailyLogs} />);
    
    const tab2 = screen.getByRole('tab', { name: 'Day 2' });
    expect(tab2).toHaveAttribute('aria-selected', 'false');
    
    fireEvent.click(tab2);
    
    expect(tab2).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/500.0 mi/)).toBeInTheDocument();
    expect(screen.getByText('No remarks for this day.')).toBeInTheDocument();
  });

  it('shows tooltip on hover', () => {
    render(<EldLogViewer dailyLogs={mockDailyLogs} />);
    
    // Find event graphics elements
    const lines = screen.getAllByRole('graphics-symbol');
    
    // Initially tooltip is hidden
    expect(screen.queryByTestId('event-tooltip')).not.toBeInTheDocument();
    
    // Hover over the second event (PICKUP)
    fireEvent.mouseEnter(lines[1]);
    
    expect(screen.getByTestId('event-tooltip')).toBeInTheDocument();
    expect(screen.getAllByText('ON DUTY NOT DRIVING')[1]).toBeInTheDocument();
    expect(screen.getByText('Loading freight')).toBeInTheDocument();
    
    // Mouse leave removes tooltip
    fireEvent.mouseLeave(lines[1]);
    expect(screen.queryByTestId('event-tooltip')).not.toBeInTheDocument();
  });
  
  it('shows tooltip on focus (keyboard accessibility)', () => {
    render(<EldLogViewer dailyLogs={mockDailyLogs} />);
    
    const lines = screen.getAllByRole('graphics-symbol');
    
    // Focus
    fireEvent.focus(lines[0]);
    expect(screen.getByTestId('event-tooltip')).toBeInTheDocument();
    
    // Blur
    fireEvent.blur(lines[0]);
    expect(screen.queryByTestId('event-tooltip')).not.toBeInTheDocument();
  });
});
