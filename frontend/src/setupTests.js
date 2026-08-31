import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

import React from 'react';

window.HTMLElement.prototype.scrollIntoView = function() {};

// Cleanup DOM after each test case
afterEach(() => {
  cleanup();
});

vi.mock('react-leaflet', () => {
  return {
    MapContainer: ({ children }) => React.createElement('div', { 'data-testid': 'map-container' }, children),
    TileLayer: () => React.createElement('div', { 'data-testid': 'tile-layer' }),
    Polyline: () => React.createElement('div', { 'data-testid': 'polyline' }),
    Marker: ({ children }) => React.createElement('div', { 'data-testid': 'marker' }, children),
    Popup: ({ children }) => React.createElement('div', { 'data-testid': 'popup' }, children),
    useMap: () => ({
      fitBounds: vi.fn(),
      flyTo: vi.fn(),
    }),
  };
});

vi.mock('leaflet', () => ({
  default: {
    latLngBounds: vi.fn(() => ({})),
    divIcon: vi.fn(),
  },
}));
