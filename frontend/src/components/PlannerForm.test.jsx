import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PlannerForm from './PlannerForm';

describe('PlannerForm Validation', () => {
  it('requires all fields', () => {
    const mockSubmit = vi.fn();
    render(<PlannerForm onSubmit={mockSubmit} disabled={false} />);
    
    // We try to submit without typing anything
    fireEvent.submit(screen.getByTestId('planner-form'));
    
    expect(screen.getByTestId('validation-error')).toHaveTextContent('All location fields are required');
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  const fillLocations = async (user) => {
    await user.type(screen.getByLabelText(/Current Location/i), 'Chicago, IL');
    await user.type(screen.getByLabelText(/Pickup Location/i), 'Indy, IN');
    await user.type(screen.getByLabelText(/Dropoff Location/i), 'Denver, CO');
  };

  it('accepts cycle 69', async () => {
    const user = userEvent.setup();
    const mockSubmit = vi.fn();
    render(<PlannerForm onSubmit={mockSubmit} disabled={false} />);
    
    await fillLocations(user);
    const cycleInput = screen.getByLabelText(/Current Cycle Used/i);
    await user.clear(cycleInput);
    await user.type(cycleInput, '69');

    fireEvent.submit(screen.getByTestId('planner-form'));
    expect(screen.queryByTestId('validation-error')).not.toBeInTheDocument();
    expect(mockSubmit).toHaveBeenCalledWith({
      current_location: 'Chicago, IL',
      pickup_location: 'Indy, IN',
      dropoff_location: 'Denver, CO',
      current_cycle_used_hours: 69
    });
  });

  it('accepts cycle 69.9', async () => {
    const user = userEvent.setup();
    const mockSubmit = vi.fn();
    render(<PlannerForm onSubmit={mockSubmit} disabled={false} />);
    
    await fillLocations(user);
    const cycleInput = screen.getByLabelText(/Current Cycle Used/i);
    await user.clear(cycleInput);
    await user.type(cycleInput, '69.9');

    fireEvent.submit(screen.getByTestId('planner-form'));
    expect(screen.queryByTestId('validation-error')).not.toBeInTheDocument();
    expect(mockSubmit).toHaveBeenCalledWith(expect.objectContaining({
      current_cycle_used_hours: 69.9
    }));
  });

  it('rejects cycle 70', async () => {
    const user = userEvent.setup();
    const mockSubmit = vi.fn();
    render(<PlannerForm onSubmit={mockSubmit} disabled={false} />);
    
    await fillLocations(user);
    const cycleInput = screen.getByLabelText(/Current Cycle Used/i);
    await user.clear(cycleInput);
    await user.type(cycleInput, '70');

    fireEvent.submit(screen.getByTestId('planner-form'));
    expect(screen.getByTestId('validation-error')).toHaveTextContent('must be between 0 and 69.9');
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  it('rejects cycle 70.1', async () => {
    const user = userEvent.setup();
    const mockSubmit = vi.fn();
    render(<PlannerForm onSubmit={mockSubmit} disabled={false} />);
    
    await fillLocations(user);
    const cycleInput = screen.getByLabelText(/Current Cycle Used/i);
    await user.clear(cycleInput);
    await user.type(cycleInput, '70.1');

    fireEvent.submit(screen.getByTestId('planner-form'));
    expect(screen.getByTestId('validation-error')).toHaveTextContent('must be between 0 and 69.9');
    expect(mockSubmit).not.toHaveBeenCalled();
  });
});
