# Milepost

**Plan the route. Know every stop.**

Milepost is a professional, HOS-aware logistics and trip-planning application engineered for property-carrying commercial motor vehicle drivers and fleet operations. It calculates compliant routing, automated fueling/rest schedules, interactive visual map geometry, chronological stop timelines, and FMCSA-structured SVG ELD daily driver logs across multi-day trips.

---

## Production Architecture

```
User Browser
     │
     ▼
[ Vercel Deployment ] (React 19 + Vite Frontend)
     │
     ▼ HTTPS API Call (VITE_API_BASE_URL)
[ Render Deployment ] (Django REST API + Gunicorn)
     ├──► [ Geocoding ] (Nominatim / OpenStreetMap)
     ├──► [ Routing ] (OSRM driving polyline & distance annotation)
     ├──► [ HOS State Engine ] (Pure Python 11h/14h/30m/70h/1000mi logic)
     └──► [ ELD Processor ] (1440-minute daily log generator & midnight splitter)
```

- **Frontend Hosting**: Deployed on **Vercel** as a static Vite Single Page Application.
- **Backend Hosting**: Deployed on **Render** as a Python WSGI Web Service (`gunicorn config.wsgi:application`).
- **Stateless Pipeline**: Zero database dependencies; requests process purely in-memory.

---

## Features

- **HOS-Aware Trip Planning**: Automatically schedules required 30-minute breaks, 10-hour off-duty resets, and fuel stops along the actual driving route.
- **Two-Leg Driving Geometry**: Handles two distinct driving legs (Origin → Pickup and Pickup → Dropoff) with mandatory 1-hour loading/unloading duty stops.
- **Interactive Route Map**: Displays exact polyline routing, location markers, stop locations, and interactive popup details powered by Leaflet & OpenStreetMap.
- **Chronological Stop Timeline**: Provides a multi-day timeline grouped by day (`DAY 1 · 09:07 | Pickup`, `DAY 2 · 10:45 | Fuel`) with bidirectional map synchronization.
- **SVG ELD Daily Driver Logs**: Visualizes standard 24-hour driver log sheets divided into 15-minute grid intervals across Off Duty, Sleeper Berth, Driving, and On Duty Not Driving statuses, including automatic remarks and duty totals.
- **Strict Compliance States**: Highlights compliant trips (`COMPLIANT`), warning states (`WARNING`), and unresolvable rule blocks (`TRIP BLOCKED`) with backend-driven explanations.

---

## HOS Model Assumptions

Milepost models property-carrying Interstate Hours of Service rules under the following assumptions:

| Parameter | Rule Value | Operational Assumption |
| :--- | :--- | :--- |
| **Driving Limit** | 11 hours | Maximum cumulative driving time allowed before a 10-hour off-duty reset. |
| **Duty Window** | 14 hours | Maximum elapsed time allowed after coming on duty before driving must cease. |
| **Rest Break** | 30 minutes | Required after 8 cumulative hours of driving without a 30+ min break. |
| **Off-Duty Reset** | 10 hours | Consecutive off-duty time required to reset 11h driving and 14h window clocks. |
| **Cycle Limit** | 70 hours / 8 days | Maximum cumulative duty time allowed in 8 days (no 34h restart modeled). |
| **Fuel Stop** | Every 1,000 miles | Mandatory 30-minute On Duty Not Driving fuel stop scheduled at or before 1,000 route miles. |
| **Loading/Unloading**| 1 hour each | Scheduled at Pickup and Dropoff locations as On Duty Not Driving time. |

---

## Deployment Configuration

### 1. Frontend Deployment (Vercel)

- **Framework Preset**: Vite
- **Build Command**: `npm run build`
- **Output Directory**: `dist`
- **Environment Variables**:
  - `VITE_API_BASE_URL`: `https://milepost-backend.onrender.com`

### 2. Backend Deployment (Render)

- **Environment**: Python 3.13
- **Build Command**: `cd backend && pip install -r requirements.txt && python manage.py collectstatic --noinput`
- **Start Command**: `cd backend && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`
- **Health Check Path**: `/api/health/`
- **Environment Variables**:
  - `DJANGO_SETTINGS_MODULE`: `config.settings.prod`
  - `DJANGO_SECRET_KEY`: `<secure-random-secret-key>`
  - `DJANGO_ALLOWED_HOSTS`: `milepost-backend.onrender.com`
  - `CORS_ALLOWED_ORIGINS`: `https://milepost.vercel.app`

---

## Local Development Setup

### 1. Backend Setup

```bash
cd backend
pip install -r requirements.txt
python -m pytest trip_planner/tests/ -v
python manage.py runserver 8000
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm test
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Environment Variables Reference

| Variable Name | Environment | Description | Example / Default |
| :--- | :--- | :--- | :--- |
| `DJANGO_SECRET_KEY` | Backend | Secret key for cryptographic signing | `<production-secret>` |
| `DJANGO_DEBUG` | Backend | Django debug flag (False in prod) | `False` |
| `DJANGO_ALLOWED_HOSTS` | Backend | Comma-separated allowed HTTP hosts | `milepost-backend.onrender.com` |
| `CORS_ALLOWED_ORIGINS` | Backend | Comma-separated allowed CORS origins | `https://milepost.vercel.app` |
| `VITE_API_BASE_URL` | Frontend | Base URL of the backend API | `https://milepost-backend.onrender.com` |

---

## Testing

```bash
# Backend tests (285 passing unit, engine, serializer, and health check tests):
cd backend
python -m pytest trip_planner/tests/ -v

# Frontend tests (21 passing component & integration tests):
cd frontend
npx vitest run --pool=threads
```

---

## Limitations & Legal Disclaimer

> **IMPORTANT DISCLAIMER**: Milepost is an operational trip-planning tool based on modeled HOS assumptions. It is **not** a certified Electronic Logging Device (ELD) under 49 CFR Part 395 Subpart B, nor is it an official legal or compliance authority. Results are provided for planning and estimation purposes under modeled parameters.
