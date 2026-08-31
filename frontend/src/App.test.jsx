import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import App from './App';

describe('App States and Integration', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const fillForm = () => {
    fireEvent.change(screen.getByLabelText(/Current Location/i), { target: { value: 'Chicago, IL' } });
    fireEvent.change(screen.getByLabelText(/Pickup Location/i), { target: { value: 'Indy, IN' } });
    fireEvent.change(screen.getByLabelText(/Dropoff Location/i), { target: { value: 'Denver, CO' } });
  };

  it('renders empty state initially', () => {
    render(<App />);
    expect(screen.getByTestId('empty-state')).toHaveTextContent('generate a complete route plan');
  });

  it('shows staged loading messages', async () => {
    // Mock an unresolved promise so it stays in loading state
    global.fetch.mockImplementation(() => new Promise(() => {}));
    
    render(<App />);
    fillForm();
    
    fireEvent.submit(screen.getByTestId('planner-form'));
    
    expect(screen.getByTestId('loading-state')).toHaveTextContent('Geocoding locations…');
    
    act(() => {
      vi.advanceTimersByTime(1200);
    });
    
    expect(screen.getByTestId('loading-state')).toHaveTextContent('Calculating route…');
  });

  it('shows success state after valid fetch', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        summary: {
          total_distance_miles: 1000,
          total_driving_hours: 15,
          total_trip_days: 2,
          cycle_remaining_at_end_hours: 50,
          fuel_stop_count: 0,
          rest_stop_count: 0
        },
        compliance: { is_compliant: true },
        stops: [],
        route: { legs: [] }
      })
    });
    
    render(<App />);
    fillForm();
    
    fireEvent.submit(screen.getByTestId('planner-form'));
    
    // We need to resolve the pending microtasks created by fetch
    await act(async () => {
      vi.runAllTimers();
    });
    
    expect(screen.getByTestId('results-dashboard')).toBeInTheDocument();
    
    expect(screen.getByText(/1,000 mi/)).toBeInTheDocument();
    expect(screen.getByText(/15h 0m/)).toBeInTheDocument();
  });

  it('shows structured error from backend', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true, // Backend returns 200 with structured errors
      json: async () => ({
        errors: [{ code: 'GEOCODING_TIMEOUT', message: 'Could not resolve Chicago, IL' }]
      })
    });
    
    render(<App />);
    fillForm();
    
    fireEvent.submit(screen.getByTestId('planner-form'));
    
    await act(async () => {
      vi.runAllTimers();
    });
    
    expect(screen.getByTestId('error-state')).toBeInTheDocument();
    expect(screen.getByTestId('error-state')).toHaveTextContent('GEOCODING_TIMEOUT');
    expect(screen.getByTestId('error-state')).toHaveTextContent('Could not resolve Chicago, IL');
  });

  it('shows network error if fetch rejects', async () => {
    global.fetch.mockRejectedValueOnce(new Error('Failed to fetch'));
    
    render(<App />);
    fillForm();
    
    fireEvent.submit(screen.getByTestId('planner-form'));
    
    await act(async () => {
      vi.runAllTimers();
    });
    
    expect(screen.getByTestId('error-state')).toBeInTheDocument();
    expect(screen.getByTestId('error-state')).toHaveTextContent('NETWORK_ERROR');
  });
});
