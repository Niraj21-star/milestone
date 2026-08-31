import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { renderToStaticMarkup } from 'react-dom/server';
import { MapPin, Fuel, Coffee, BedDouble, ArrowRight } from 'lucide-react';

const MapBounds = ({ geometry, selectedStopId, stops }) => {
  const map = useMap();

  useEffect(() => {
    if (geometry && geometry.length > 0) {
      const bounds = L.latLngBounds(geometry.map(pt => [pt.lat, pt.lon]));
      map.fitBounds(bounds, { padding: [50, 50] });
    }
  }, [geometry, map]);

  useEffect(() => {
    if (selectedStopId && stops) {
      const stop = stops.find(s => s.id === selectedStopId);
      if (stop && stop.location) {
        map.flyTo([stop.location.lat, stop.location.lon], 13, { duration: 1 });
      }
    }
  }, [selectedStopId, stops, map]);

  return null;
};

const createIcon = (type, isSelected) => {
  let IconComponent = MapPin;
  let color = '#1e293b';
  let size = 24;

  switch (type) {
    case 'ORIGIN':
      IconComponent = ArrowRight;
      color = '#10b981';
      break;
    case 'DESTINATION':
      IconComponent = MapPin;
      color = '#ef4444';
      break;
    case 'FUEL':
      IconComponent = Fuel;
      color = '#f59e0b';
      break;
    case 'REST':
      IconComponent = BedDouble;
      color = '#64748b';
      break;
    case 'BREAK':
      IconComponent = Coffee;
      color = '#64748b';
      break;
    default:
      IconComponent = MapPin;
      break;
  }

  const iconMarkup = renderToStaticMarkup(
    <div style={{
      backgroundColor: isSelected ? color : '#fff',
      border: `2px solid ${color}`,
      color: isSelected ? '#fff' : color,
      borderRadius: '50%',
      width: '32px',
      height: '32px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxShadow: isSelected ? '0 0 10px rgba(0,0,0,0.3)' : '0 2px 4px rgba(0,0,0,0.1)',
      transform: isSelected ? 'scale(1.2)' : 'scale(1)',
      transition: 'all 0.2s ease'
    }}>
      <IconComponent size={18} />
    </div>
  );

  return L.divIcon({
    html: iconMarkup,
    className: 'custom-map-icon',
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    popupAnchor: [0, -16]
  });
};

export default function RouteMap({ route, stops, selectedStopId }) {
  if (!route || !route.legs || route.legs.length === 0) return null;

  // Flatten geometry
  const geometry = [];
  route.legs.forEach(leg => {
    if (leg.geometry) {
      geometry.push(...leg.geometry);
    }
  });

  return (
    <div className="card" style={{ height: '600px', padding: 0, overflow: 'hidden' }}>
      <MapContainer 
        center={[39.8283, -98.5795]} 
        zoom={4} 
        style={{ height: '100%', width: '100%', zIndex: 0 }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        
        <Polyline 
          positions={geometry.map(pt => [pt.lat, pt.lon])} 
          color="var(--color-primary)" 
          weight={4} 
          opacity={0.8}
        />

        {stops && stops.map(stop => {
          if (!stop.location || !stop.location.lat) return null;
          return (
            <Marker 
              key={stop.id} 
              position={[stop.location.lat, stop.location.lon]}
              icon={createIcon(stop.map_marker_type, stop.id === selectedStopId)}
            >
              <Popup>
                <div style={{ minWidth: '150px' }}>
                  <h4 style={{ margin: '0 0 4px 0' }}>{stop.map_marker_type}</h4>
                  <p style={{ margin: 0, fontSize: '12px' }}>
                    <strong>Time:</strong> {new Date(stop.start_time).toLocaleTimeString([], {hour: 'numeric', minute:'2-digit'})}<br/>
                    <strong>Mileage:</strong> {stop.mileage_start.toFixed(1)} mi<br/>
                    <strong>Duration:</strong> {stop.duration_minutes} min
                  </p>
                  <p style={{ margin: '8px 0 0 0', fontSize: '12px', color: '#666' }}>
                    {stop.explanation}
                  </p>
                </div>
              </Popup>
            </Marker>
          );
        })}

        <MapBounds geometry={geometry} selectedStopId={selectedStopId} stops={stops} />
      </MapContainer>
    </div>
  );
}
