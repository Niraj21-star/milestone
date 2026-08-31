# Milepost — Final Implementation Specification

Tagline: Plan the route. Know every stop.

This document is the single source of truth for implementation. Do not add features, inputs, or requirements not present here.

---

## 1. Project Objective

Build a full-stack application (Django + React) that accepts four inputs and produces a route, an HOS-compliant stop schedule, and computed multi-day ELD daily log sheets.

**Inputs (exactly these four, no more):**
- Current Location
- Pickup Location
- Dropoff Location
- Current Cycle Used (Hrs)

**Outputs:**
- Route (distance, estimated travel duration, geometry) via a free map API
- Stops: fuel stops, mandatory rest/break stops, pickup operation, dropoff operation
- HOS schedule (full event timeline)
- Compliance state (COMPLIANT / WARNING / BLOCKED)
- Daily ELD log sheets, drawn on a 24-hour grid, one or more sheets for multi-day trips

---

## 2. Source of Truth Categories

Every behavior in this document is tagged:
- **[SPOTTER]** — stated explicitly in the Spotter assessment instructions.
- **[FMCSA]** — derived from the supplied Interstate Truck Driver's Guide to Hours of Service.
- **[DECISION]** — an implementation decision made because the assessment materials do not specify this detail. Never presented as a Spotter or FMCSA requirement.

---

## 3. Locked Assessment Assumptions [SPOTTER]

- Property-carrying driver.
- **70-hour/8-day** cycle (not 60/7).
- **No adverse driving conditions** exception is modeled.
- Fueling **at least once every 1,000 miles**.
- **1 hour** for pickup, **1 hour** for dropoff.

No other assumptions are added silently. Any additional assumption below is explicitly marked **[DECISION]**.

---

## 4. Cycle Hours Input Limitation [DECISION, constrained by input shape]

The assessment provides only a single scalar: `Current Cycle Used (Hrs)`. It does not provide the historical distribution of on-duty hours across the previous 8 days.

```
remaining_cycle_minutes = 70*60 - current_cycle_used_hours*60
```

Rules:
- The application must **never** invent a historical daily-hours distribution or simulate when past hours "roll off" the 8-day window.
- The application must **never** automatically insert a 34-hour restart to manufacture cycle capacity that wasn't demonstrated.
- `remaining_cycle_minutes` decreases monotonically as the simulated trip consumes DRIVING and ON_DUTY_NOT_DRIVING minutes. It is never replenished mid-simulation.
- If a trip cannot fit within available cycle capacity, the result is **BLOCKED** (§24), not a silently-completed illegal plan.
- If `current_cycle_used_hours >= 70` at input time, reject at request validation before simulation starts.

---

## 5. Deterministic Trip Start [DECISION]

The assessment provides no start-date/time input.

**Trip start = `00:00` on the current date, in the timezone of the origin (current) location.**

Rationale: a fixed, deterministic start makes output reproducible for testing and for assessment grading — the evaluator can run the same inputs twice and get identical results. No additional input field is added for this.

---

## 6. HOS Clock Model [FMCSA]

Four independent clocks:

| Clock | Consumed by | Reset by | NOT reset by | Limit |
|---|---|---|---|---|
| A. Driving clock | Every DRIVING minute | A 10-consecutive-hour OFF_DUTY period | Midnight / calendar date change | 11 hours |
| B. 14-hour duty window | Every wall-clock minute once the duty period starts, regardless of status | A 10-consecutive-hour OFF_DUTY period | Midnight / calendar date change | 14 hours — this is a **window**, not a "daily limit"; it is not tied to the calendar day |
| C. 30-minute break clock | Every DRIVING minute (tracks driving minutes since last qualifying break) | Any single consecutive ≥30-minute block of OFF_DUTY or ON_DUTY_NOT_DRIVING | Midnight | Must not exceed 8 hours of driving before the next qualifying break |
| D. 70-hour/8-day cycle | Every DRIVING and ON_DUTY_NOT_DRIVING minute | Never reset mid-simulation (§4) | Midnight | 70 hours, seeded from `current_cycle_used_hours` |

**A midnight boundary is only an ELD/calendar-sheet boundary. It never resets any of clocks A–D.**

---

## 7. Modeled HOS Rules [FMCSA]

- 11-hour driving limit within a 14-hour duty window, both reset only by a 10-consecutive-hour off-duty period.
- 30-minute break required after 8 cumulative hours of driving; may be satisfied by any qualifying non-driving event (§8).
- 70-hour/8-day on-duty cycle limit, handled per §4/§24.
- 10-hour off-duty period required once the 11-hour driving limit or 14-hour window is reached (§9).

**Explicitly not modeled** (not required by the Spotter assumptions in §3):
- Adverse driving conditions exception.
- Team/multi-driver driving.
- Sleeper-berth split-duty provision.
- Short-haul exceptions (150-air-mile, 16-hour, non-CDL).
- 34-hour restart automation (§4).

---

## 8. Break Qualification — State Machine Rule [FMCSA + DECISION]

```
is_break_qualifying(event) =
    event.type in {OFF_DUTY, ON_DUTY_NOT_DRIVING}
    AND event.duration_minutes >= 30
```

Modeled durations [SPOTTER + DECISION]:
- Fuel = 30 minutes, ON_DUTY_NOT_DRIVING.
- Pickup = 60 minutes, ON_DUTY_NOT_DRIVING.
- Dropoff = 60 minutes, ON_DUTY_NOT_DRIVING.

Whenever the engine is about to insert any non-driving event, it checks `is_break_qualifying`. If true, Clock C resets to 0 at that event's end and **no separate/redundant 30-minute break is scheduled**. A dedicated break (reason `30_min_break`) is only inserted when Clock C would reach 8 hours of driving before the next naturally-occurring qualifying event (fuel, pickup, or dropoff) is due.

**Per-segment priority (earliest-triggering constraint wins):**
1. Fuel threshold (cumulative miles since last fuel reaches 1,000.0)
2. Scheduled pickup/dropoff arrival
3. Clock C reaches 8h driving → insert 30-min break
4. Clock A reaches 11h or Clock B reaches 14h → insert 10-hour OFF_DUTY reset
5. Clock D would go negative → BLOCKED, halt simulation, return partial plan (§24)

---

## 9. 10-Hour Reset [FMCSA + DECISION]

The required off-duty period is modeled as **OFF_DUTY** (not SLEEPER_BERTH). Rationale [DECISION]: the sleeper-berth split-duty provision is explicitly not implemented (§7), so labeling resets SLEEPER_BERTH would be cosmetic only and not reflect any different engine behavior. OFF_DUTY is the simpler, honest representation.

- Resets Clock A (driving) and Clock B (14-hour window) to zero.
- Does not reset Clock D (cycle) — cycle hours are only ever consumed, never replenished mid-trip (§4).
- A midnight transition during a 10-hour reset does not itself do anything to HOS clocks — see §20.

---

## 10. Trip Order [SPOTTER]

Fixed sequence: **Current Location → Pickup Location → Dropoff Location.**

- Pickup occurs at the pickup location; dropoff occurs at the dropoff location.
- Both are ON_DUTY_NOT_DRIVING and consume the 14-hour window (Clock B) and cycle (Clock D), but **not** the 11-hour driving limit (Clock A).
- The two driving legs (current→pickup, pickup→dropoff) are simulated through one continuous clock state — no clock resets at pickup.
- If Clock A/B would be exceeded before reaching pickup or dropoff, a 10-hour OFF_DUTY reset (§9) is inserted first, and driving resumes toward the same destination afterward.
- If Clock D would go negative before reaching pickup or dropoff, the trip is BLOCKED (§24) at that point.

---

## 11. Fuel Logic [SPOTTER + DECISION]

- `miles_since_fuel` is a decimal float (1 decimal place), incremented continuously across both driving legs.
- Trigger: the instant `miles_since_fuel` would reach `1000.0` mid-segment, the segment is truncated at exactly that decimal-mile point and a fuel event is inserted; `miles_since_fuel` resets to `0.0`.
- First fuel stop occurs **at or before** 1,000.0 miles, never after.
- If total route mileage is under 1,000.0 miles, no fuel stop occurs.
- Multiple fuel stops repeat the same logic; `miles_since_fuel` tracks cumulative mileage continuously across both legs (pickup does not reset it).
- Fuel duration = 30 minutes, ON_DUTY_NOT_DRIVING, reason `fuel`.
- Fuel does not reset Clocks A, B, or D. It resets Clock C if `is_break_qualifying` (always true at 30 min) — see §8 for the no-redundant-break behavior this produces.

---

## 12. Time and Distance Precision

- **Time: integer minutes** throughout the engine — no floating-point time arithmetic, to avoid drift across a multi-day simulation.
- **Distance: decimal miles, one decimal place**, throughout the engine, API, and event model. Integer-mile truncation is not used anywhere, because it would allow the 1,000-mile fuel threshold to fire early or late by rounding error.

---

## 13. Routing Architecture [DECISION, free-API constraint from SPOTTER]

- **Routing:** OSRM (public demo router), returning geometry, decimal distance, and duration for each leg.
- **Geocoding:** Nominatim (OpenStreetMap), backend-proxied, throttled to ~1 req/sec, results cached per unique input string within a request.
- **Map visualization:** Leaflet + OpenStreetMap tiles (no API key required).
- All three integrations are called **only from Django**; React never calls them directly and contains no routing/business logic.
- **Error handling:** every external call wrapped in a try/except with a timeout (5s) and one retry. On persistent failure, the API returns a structured error object (`errors: [{code, message}]`), never a raw 500 or an unhandled exception. The frontend renders a dedicated error state (§32), never a blank screen or stack trace.
- Two legs are fetched: `current → pickup` and `pickup → dropoff`.

---

## 14. Route Geometry / Stop Interpolation [DECISION]

Every generated fuel/rest/break/pickup/dropoff stop must have a coordinate that lies on the actual displayed route — never an arbitrary nearby city.

Procedure:
1. For each leg's OSRM geometry (ordered coordinate vertices), compute **cumulative distance at each vertex** via haversine summation (decimal miles).
2. When a non-driving event (fuel, 10-hour reset, 30-min break) is triggered mid-segment at some target cumulative distance, locate the two consecutive vertices whose cumulative distances bracket that target.
3. Linearly interpolate latitude/longitude between those two vertices, proportional to the fractional distance between them.
4. The resulting coordinate is the event's `location`. `location.source = "route_interpolated"`.
5. Pickup and dropoff events use the exact geocoded pickup/dropoff coordinates. `location.source = "geocoded"`.
6. Attempt reverse geocoding (Nominatim) on interpolated coordinates to produce a human-readable `label`. On reverse-geocode failure, fall back to the nearest named waypoint/label available from the OSRM response, or a formatted coordinate string as last resort. `location.source = "fallback"` in that case. Reverse-geocode failure never fails trip planning — it only degrades the label.

---

## 15. TripEvent Model

```json
{
  "id": "evt_0007",
  "type": "DRIVING | OFF_DUTY | ON_DUTY_NOT_DRIVING",
  "reason": "start | drive_to_pickup | pickup | drive_to_dropoff | dropoff | fuel | 30_min_break | 10hr_reset | day_fill",
  "start_time": "2026-09-02T00:00:00-05:00",
  "end_time": "2026-09-02T06:30:00-05:00",
  "duration_minutes": 390,
  "day_index": 0,
  "location": {
    "lat": 35.2231,
    "lon": -101.8313,
    "label": "Amarillo, TX",
    "source": "route_interpolated | geocoded | fallback"
  },
  "mileage_start": 611.4,
  "mileage_end": 611.4,
  "clocks_after": {
    "driving_min": 390,
    "window_min": 390,
    "since_break_min": 390,
    "cycle_used_min": 3120
  },
  "explanation": "Fuel stop scheduled after 1,000.0 route miles.",
  "map_marker_type": "fuel",
  "is_rendering_only": false
}
```

- Type enum: `{DRIVING, OFF_DUTY, ON_DUTY_NOT_DRIVING}`. SLEEPER_BERTH is not an active event type in this implementation (§9) but is drawn as an empty row on the ELD grid for form fidelity (§18).
- `clocks_after` is a snapshot of all four clocks immediately after this event, so the frontend never has to recompute HOS state.
- `explanation` is generated deterministically from the actual triggering clock values (§25) — never free-text/generative.
- `map_marker_type` decouples map iconography from the internal `reason` enum.
- `is_rendering_only: true` marks synthetic day-fill events (§21) — these carry no independent `clocks_after` change (they inherit the prior real event's snapshot) and never appear in the canonical timeline (§16), only in `daily_logs[].events`.

---

## 16. Canonical Event Timeline

- The backend maintains one continuous `events[]` list — the output of the HOS simulation (§6–§11) — which is deterministic given the same inputs and never resets at midnight.
- This canonical list is used for HOS math, the map, and the stop timeline. Midnight-split and day-fill events (§20–§21) exist only in a derived `daily_logs[]` structure, never in this canonical list.

**Validation invariants** (enforced by automated tests, §33):
- No event has negative or zero duration (except explicitly zero-length boundary artifacts, which are disallowed — all events must have `duration_minutes >= 1`, except day-fill events which may be zero-length when the trip starts exactly at 00:00).
- No two canonical events overlap in time.
- Events are strictly chronologically ordered.
- Clock A never exceeds 660 minutes (11h) at any point without a reset event immediately following.
- Clock B never exceeds 840 minutes (14h) at any point without a reset event immediately following.
- Clock D (`cycle_used_min`) never exceeds `70*60` in any committed event; if it would, the simulation halts and returns BLOCKED instead of committing an over-limit event.
- No `is_rendering_only: true` event ever appears in the canonical `events[]` list or contributes to any `clocks_after` value.

---

## 17. ELD Rendering Approach

**SVG** is used for the ELD daily sheet. Rationale: the grid requires precise, computed coordinate positioning of horizontal duty-status lines and vertical transition lines — exactly what SVG path/line primitives are built for. It scales cleanly via `viewBox` without pixel-density concerns (unlike Canvas), and it can express the exact stair-step transition drawing shown in the supplied FMCSA sample grid without reconstructing table-cell borders (unlike HTML/CSS). Full PDF generation is unnecessary engineering overhead for this assessment; an SVG-to-print/PDF export is a P2 nice-to-have (§39), not a rendering requirement.

The ELD is generated **entirely from backend event data** returned by the API. No sample lines, placeholder grids, or hard-coded coordinates are used anywhere in the renderer.

---

## 18. ELD Daily Sheet Requirements

Each daily sheet represents a complete **24-hour / 1,440-minute** period (§21), matching the supplied Driver's Daily Log reference.

Rows, top to bottom, matching the FMCSA form order:
1. OFF_DUTY
2. SLEEPER_BERTH (drawn as an empty row for form fidelity — no line is ever drawn here in this implementation, since SLEEPER_BERTH is not an active event type per §9/§15)
3. DRIVING
4. ON_DUTY_NOT_DRIVING

Render, per sheet:
- Horizontal grid lines and vertical time markers.
- 15-minute tick marks (light) and hourly labels (heavy), spanning Midnight → 23 → Midnight, matching the reference form's axis.
- Horizontal duty-status lines per event.
- Vertical transition lines connecting consecutive events of differing status.
- Remarks row (§23).
- Totals per status (§22).
- Date, and mileage/trip fields as available from the API response, positioned per the reference layout (header fields outside the grid, as shown in the supplied blank log).

---

## 19. ELD Coordinate System

```
x(minute_of_day) = minute_of_day        // 0..1440, 1 unit per minute
y_center(status)  = ROW_Y[status] + ROW_HEIGHT / 2
```

The SVG uses a `viewBox="0 0 1440 <total_height>"` so the logical coordinate system is always 1 unit = 1 minute regardless of rendered pixel size — the viewBox, not hard-coded pixel widths, is the source of scale. Row order and `ROW_Y` values follow §18.

**Line generation**, per day's (midnight-split, day-filled) event list, in chronological order:
1. For each event: draw a horizontal line at `y = y_center(event.type)` from `x = start_minute_of_day` to `x = end_minute_of_day`.
2. If the previous event's type differs from the current one, draw a vertical connector line at `x = start_minute_of_day` between the two events' `y_center` values.
3. Tick marks and hour labels are generated once per sheet, independent of event data.

---

## 20. Midnight Handling

The canonical simulation (§16) is midnight-agnostic and fully continuous. A **separate post-processing step** produces `daily_logs[]`:

For any canonical event whose `start_time` and `end_time` fall on different calendar dates (in the fixed origin timezone, §5):

```
split(event, boundary):
  event_a = copy(event); event_a.end_time = boundary
  event_b = copy(event); event_b.start_time = boundary
  both inherit reason/location/explanation; day_index differs by 1
```

- Example: an event `23:00 → 03:00` becomes Day N `23:00 → 24:00` and Day N+1 `00:00 → 03:00`.
- This split affects only the `daily_logs[]` representation. It does not alter, re-trigger, or reset any HOS clock (§6) — midnight is a calendar/rendering boundary only.

---

## 21. 24-Hour ELD Fill (Rendering-Only Layer)

Because the actual trip may occupy only part of the first and/or last calendar day, each daily sheet must still visually cover the full 24 hours.

- For the first day: if the earliest real event does not start at `00:00`, insert a synthetic OFF_DUTY event (`reason: "day_fill"`, `is_rendering_only: true`) from `00:00` to the first real event's start. (Under §5's deterministic-start rule this is normally zero-length, since the trip always starts at `00:00`; the mechanism exists to remain correct if that rule ever changes.)
- For the last day: if the final real event does not end at `24:00`, insert a synthetic day-fill OFF_DUTY event from the final real event's end to `24:00`.

Hard requirements:
- Day-fill events exist **only** in `daily_logs[].events` — never in the canonical `events[]` timeline (§16).
- Day-fill events never enter any HOS clock calculation and never appear with `clocks_after` values of their own (they inherit the prior real event's snapshot for display continuity only).
- Day-fill events never trigger a fake 10-hour reset or any other clock reset.

---

## 22. ELD Totals

For every daily sheet, compute (from actual §20/§21-processed events, never hard-coded):

```
totals_minutes = {
  "OFF_DUTY": sum(duration_minutes for e in day.events if e.type == "OFF_DUTY"),   // includes day_fill minutes
  "SLEEPER_BERTH": 0,   // always zero — event type never emitted in this implementation
  "DRIVING": sum(...),
  "ON_DUTY_NOT_DRIVING": sum(...)
}
```

`sum(totals_minutes.values())` must equal exactly **1440** for every day. This is enforced by an automated test (§33), not a manual check.

---

## 23. ELD Remarks

Generated from real events, not decorative placeholders:

```
pickup       → "Pickup"
dropoff      → "Dropoff"
fuel         → "Fuel"
30_min_break → "30-Min Break"
10hr_reset   → "10-Hr Reset"
```

- Label = `event.location.label` (§14).
- Remarks are drawn only at non-driving, non-`day_fill` status transitions, to keep the grid readable and match the density of the supplied FMCSA sample (which annotates meaningful stops, not every mile).

---

## 24. Compliance Model

```
COMPLIANT: trip fully planned to dropoff; remaining cycle capacity at trip end > 10% of 70h (7h); no BLOCKED condition encountered.
WARNING:   trip fully planned to dropoff; remaining cycle capacity at trip end <= 7h (10% of 70h) — surfaced explicitly, not hidden.
BLOCKED:   simulation halted before reaching dropoff because Clock D (cycle) would go negative (§4/§8/§16). A partial plan (events up to the block point) is still returned.
```

UI/API copy: **"Compliant under modeled HOS assumptions."** The application never claims FMCSA certification, legal guarantee, or official ELD certification — this wording appears in the results header and in the README's limitations section (§37).

---

## 25. Deterministic Stop Explanations

Every non-driving event's `explanation` is generated from a fixed template filled with the exact values from `clocks_after` (§15) — never free-text or model-generated:

```
fuel         → "Fuel stop scheduled after {mileage_since_last_fuel:.1f} route miles."
30_min_break → "30-minute driving interruption required after {driving_minutes_since_break/60:.1f} cumulative hours of driving."
10hr_reset   → "10-hour off-duty period required — {trigger} reached ({clock_value}/{limit})."
                 // trigger = "11-hour driving limit" or "14-hour duty window"
pickup       → "Scheduled 1-hour pickup operation."
dropoff      → "Scheduled 1-hour dropoff operation."
```

---

## 26. API Contract

```
POST /api/plan-trip/

Request:
{
  "current_location": "Chicago, IL",
  "pickup_location": "Indianapolis, IN",
  "dropoff_location": "Denver, CO",
  "current_cycle_used_hours": 12.5
}

Response 200:
{
  "trip_start_time": "2026-09-02T00:00:00-05:00",
  "route": {
    "legs": [
      { "from": "current", "to": "pickup", "distance_miles": 165.3, "duration_minutes": 165, "geometry": [ {"lat":..., "lon":..., "cumulative_distance_miles":...}, ... ] },
      { "from": "pickup", "to": "dropoff", "distance_miles": 1020.7, "duration_minutes": 960, "geometry": [ ... ] }
    ],
    "total_distance_miles": 1186.0,
    "total_driving_minutes": 1125
  },
  "events": [ /* canonical TripEvent list, §15 schema, is_rendering_only=false throughout */ ],
  "daily_logs": [
    {
      "day_index": 0,
      "date": "2026-09-02",
      "events": [ /* midnight-split + day_fill events, §20-§21, full 1440-min coverage */ ],
      "totals_minutes": { "OFF_DUTY": 780, "SLEEPER_BERTH": 0, "DRIVING": 480, "ON_DUTY_NOT_DRIVING": 180 }
    }
  ],
  "stops": [ /* non-driving, non-day_fill events, flattened for map/timeline use */ ],
  "summary": {
    "total_distance_miles": 1186.0,
    "total_driving_hours": 18.75,
    "total_trip_days": 2,
    "fuel_stop_count": 1,
    "rest_stop_count": 1,
    "cycle_used_at_start_hours": 12.5,
    "cycle_remaining_at_end_hours": 33.25
  },
  "compliance": { "status": "COMPLIANT", "message": "Compliant under modeled HOS assumptions." },
  "warnings": [],
  "errors": []
}
```

On BLOCKED or upstream (routing/geocoding) failure: same response shape; `events`/`daily_logs`/`summary` reflect the successfully-planned partial trip (if any), `compliance.status` is `BLOCKED` where applicable, and `errors[]` is populated with `{code, message}` objects. React renders directly from this response; it performs no HOS, distance, or clock computation of its own.

---

## 27. Backend Architecture

```
backend/
└── trip_planner/
    ├── views.py           // thin: validate request, call services, return serialized response
    ├── serializers.py
    └── services/
        ├── hos_engine.py   // pure Python, no Django imports — clocks, event generation, §6-§11, §16
        ├── routing.py       // OSRM client, cumulative-distance annotation, interpolation (§13-§14)
        ├── geocoding.py      // Nominatim client, reverse-geocode with fallback (§14)
        └── eld.py             // midnight-split + day-fill construction + totals validation (§20-§22)
```

- No database, no models, no migrations — fully stateless per request.
- No authentication.
- No microservices — one Django app is sufficient for this scope.

---

## 28. Frontend Architecture

React + Vite. Component structure:

```
<PlannerForm />                    // 4 inputs (§1), client-side validation, submit
<ResultsDashboard>
  <StatsHeaderStrip />             // distance, driving hrs, days, fuel/rest counts, cycle remaining
  <ComplianceBanner />             // COMPLIANT/WARNING/BLOCKED, §24 wording
  <NextActionCard />                // first upcoming non-driving stop + its explanation (§25)
  <RouteMap />                     // Leaflet: polyline (both legs concatenated) + interpolated stop markers
  <StopTimeline />                 // ordered stop cards; click lifts selectedStopId
  <EldLogViewer>
    <EldDaySheetTabs />
    <EldDaySheet />                 // SVG per day_index, §17-§23
  </EldLogViewer>
</ResultsDashboard>
<LoadingState /> <ErrorState /> <EmptyState />
```

- `selectedStopId` is lifted to `ResultsDashboard` and shared by `RouteMap` and `StopTimeline` for click-to-highlight interaction (§31).
- No component performs HOS math, distance math, or clock logic — all values are read directly from the API response (§26).

---

## 29. UI / UX Design System

Product name: **Milepost**. Tagline: **Plan the route. Know every stop.**

Design goals: professional, operational, trustworthy, precise, modern, data-dense but readable — a logistics/dispatch tool, not a consumer app or a generic admin template.

Avoid: excessive gradients, glassmorphism, oversized hero sections, unnecessary animation, excessive rounded corners, decorative clutter.

- **Typography:** Inter or system-ui, neutral and highly legible at small sizes.
- **Spacing:** 4px base scale (4/8/12/16/24/32).
- **Color system:** deep navy as primary, warm amber as accent/warning, forest green = compliant, red = blocked/error. Navy+amber reads as serious/DOT-adjacent without copying any real brand, and echoes the navy branding of the supplied FMCSA guide itself.
- **Cards:** flat, 1px border, minimal shadow (shadow reserved for the stats header strip only).
- **Buttons/inputs:** simple, small border-radius (4–6px), clear focus states.
- **Status indicators:** solid-color badges/dots, not gradients.
- **Icons:** one consistent icon set for stop types (fuel, rest, pickup, dropoff).
- **Responsive:** desktop is the primary target (a dispatcher at a desk is the assumed user). Tablet: map and timeline stack vertically. Mobile: stats strip becomes horizontally scrollable; ELD sheets scroll horizontally within their container rather than compressing the 1,440-minute grid.

---

## 30. Results Page Hierarchy

```
Stats (StatsHeaderStrip)
↓
Compliance (ComplianceBanner)
↓
Next Required Action (NextActionCard)
↓
Map + Timeline (RouteMap + StopTimeline, side by side on desktop)
↓
HOS Summary (part of StatsHeaderStrip / summary object)
↓
ELD (EldLogViewer)
```

This ordering answers, top to bottom: Where am I going? → Is this compliant? → What happens next? → What does the route look like and where are the stops? → What's the full picture? → What does each day's log look like?

---

## 31. Map + Timeline Interaction

Clicking a stop card in `StopTimeline` sets `selectedStopId` (shared state in `ResultsDashboard`), which `RouteMap` observes to pan to and open the corresponding marker's popup. This uses only data already present in the API response — no duplicate HOS or distance logic in the frontend.

---

## 32. Loading / Error / Empty States

**Loading (staged, time-estimated, not real backend progress events):**
"Finding your locations…" → "Planning your route…" → "Calculating HOS schedule…" → "Generating daily logs…"

**Error states:**
- Invalid/unfound location → "We couldn't find '<input>' — try a more specific city, state."
- Routing service failure → "Route service is temporarily unavailable — please try again in a moment."
- Geocoding failure → same pattern, specific to the failing field.
- BLOCKED trip is **not** an error state — it renders the full results page with the compliance banner (§24), including the partial plan.

**Empty state (before first submission):** "Enter a trip to generate a route and compliant daily logs."

No raw stack traces or unhandled exceptions are ever shown to the user.

---

## 33. Testing Strategy

Unit tests on `hos_engine.py`, each asserting the **actual event sequence** (type, reason, duration, decimal mileage, `clocks_after` values) — not just HTTP 200:

- Short trip (<300mi)
- ~500mi
- ~800mi
- Exactly 1,000.0mi (fuel boundary, decimal-precision check)
- >1,000mi, multiple fuel stops
- Multi-day trip
- Exact 8-hour driving threshold (break fires precisely)
- Exact 11-hour threshold (reset fires precisely)
- Exact 14-hour threshold (reset fires precisely)
- `cycle_used = 0`
- `cycle_used = 65`
- `cycle_used = 68`
- `cycle_used = 70` (rejected at validation)
- `cycle_used > 70` (rejected at validation)
- Fuel event satisfies the break requirement (no redundant break inserted)
- Pickup event satisfies the break requirement
- Dropoff event satisfies the break requirement
- Midnight-crossing event → correct split (§20), day totals sum to 1440 (§22)
- Day-fill correctness on first/last day (§21)
- Stop coordinate interpolation correctness (§14) — interpolated point lies between the correct geometry vertices, proportional to distance
- Reverse-geocode failure → fallback label used, trip planning still succeeds
- Routing API failure (mocked) → structured error returned, no unhandled 500
- Geocoding API failure (mocked) → same

---

## 34. Engineering Invariants

The system must never produce:
- Negative or invalid event durations
- Overlapping canonical events
- Non-chronological event ordering
- Driving time over 11 hours within an unreset window, or duty window over 14 hours
- Cycle usage (`cycle_used_min`) exceeding `70*60` in any committed canonical event
- ELD daily totals other than exactly 1,440 minutes
- Stop coordinates that do not lie on the displayed route geometry
- Rendering-only (`is_rendering_only: true`) events that affect any HOS clock or appear in the canonical timeline

---

## 35. Demo Scenarios

1. **Simple, compliant, single day.** Short route (~300–400mi), no fuel stop, at most one break. Demonstrates the happy path quickly.
2. **Long multi-day trip.** Route >1,000mi requiring at least one fuel stop and at least one 10-hour reset, producing 2–3 ELD sheets. Demonstrates the full engine and ELD rendering.
3. **High cycle usage.** Same long route as #2, with `current_cycle_used_hours` set near 65–68, to demonstrate the WARNING or BLOCKED compliance path and the partial-plan behavior.

Realistic US city pairs should be used for these three, but the application must support arbitrary valid locations, not just the demo set.

---

## 36. Deployment

- **Frontend:** Vercel-compatible build (Vite production build), `VITE_API_BASE_URL` env var pointing to the deployed backend.
- **Backend:** any Django-compatible production host (e.g., Render, Railway). Split settings (`base.py` / `prod.py`), `DEBUG=False` in production, `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` set from environment variables.
- No API keys required for OSRM/Nominatim/Leaflet (all free/keyless). The only secret is `SECRET_KEY` (and a `DATABASE_URL` only if persistence is added later — not required by this spec).
- `.env.example` is committed; actual `.env` files are gitignored; real values are set in the hosting platform's dashboard. No secrets are ever committed to GitHub.

---

## 37. GitHub / README Structure

```
README.md sections:
- Project overview
- Features
- Architecture (with a simple diagram)
- HOS assumptions (§3, §4, §5, verbatim)
- Routing approach (§13-§14)
- ELD generation approach (§17-§23)
- API documentation (§26)
- Setup instructions
- Environment variables
- Testing instructions (§33)
- Deployment (§36)
- Known limitations (no sleeper-berth split, no 34-hour restart, no historical cycle-hours modeling, no adverse-conditions exception, not a certified ELD product — §24)
```

Kept concise and professional — architectural reasoning, not a restatement of this entire spec.

---

## 38. Loom Script (3–5 minutes)

0:00–0:20 — Problem framing.
0:20–0:50 — Input demo (submit demo scenario #2).
0:50–1:40 — Map, route, stop markers.
1:40–2:30 — Click a stop; show its deterministic explanation (§25) and the map/timeline sync (§31).
2:30–3:30 — ELD logs: flip through multiple days, point at a specific transition line and match it to the underlying event; mention the midnight split (§20).
3:30–4:00 — Cycle-warning scenario (#3); show the compliance banner and explain the decision not to fabricate roll-off data (§4).
4:00–4:30 — One architecture decision: the pure-function HOS engine, tested in isolation from Django/React.
4:30–5:00 — Close.

The ELD is the visual centerpiece of the demo.

---

## 39. Scope Control

**P0 — MUST BUILD**
- HOS engine (§6–§11, §16) with unit tests (§33)
- TripEvent model, midnight split, day-fill (§15, §20–§22)
- ELD SVG renderer, multi-day (§17–§19, §23)
- Routing/geocoding integration with graceful failure (§13–§14)
- Results dashboard: stats strip, compliance banner, next-action card, map, timeline, ELD viewer (§28–§30)
- Map↔timeline click sync (§31)
- Compliance model (§24)
- Loading/error/empty states (§32)
- Hosted deploy, README, Loom (§36–§38)

**P1 — SHOULD BUILD (if on schedule by roughly the two-thirds mark of the 16-hour budget)**
- Responsive tablet/mobile layout polish (§29)

**P2 — ONLY IF TIME REMAINS**
- PDF export of a single day's ELD sheet (print stylesheet over the existing SVG)
- Documented (not necessarily working) self-hosted OSRM fallback note in the README

**DO NOT BUILD**
- Authentication / user accounts
- Database persistence of trips
- Sleeper-berth split-duty provision
- 34-hour restart automation
- Adverse driving conditions exception
- Multi-driver / team driving
- Real-time traffic
- Weather integration
- Non-trivial animation

---

## 40. Implementation Order

1. Project foundation (Django + React scaffolds, env config, deploy pipeline stubbed early)
2. HOS engine (§6–§11, §16) — pure functions
3. HOS engine unit tests (§33) — written and passing before moving on
4. Routing/geocoding integration (§13–§14)
5. ELD processor: midnight-split + day-fill + totals validation (§20–§22)
6. `/api/plan-trip/` endpoint (§26), wired end-to-end, manually verified against the three demo scenarios (§35)
7. React planner form (§28)
8. Map component (§28, §31)
9. Stop timeline component (§28, §31)
10. SVG ELD renderer (§17–§19, §23) — highest-scrutiny artifact; checkpoint here before further polish
11. Compliance banner + next-action card (§24–§25)
12. UX polish: loading/error/empty states, responsive pass (§32, §29 P1)
13. Integration testing across all three demo scenarios on the real (non-mocked) stack
14. Deployment (§36)
15. README (§37)
16. Loom (§38)

---

## 41. Specification Self-Audit

- HOS model is deterministic: fixed trip start (§5), fixed clock rules (§6–§11), no randomness anywhere.
- No unsupported assumptions: every rule is tagged [SPOTTER], [FMCSA], or [DECISION] (§2); adverse conditions, sleeper-berth split, and 34-hour restart are explicitly excluded (§7, §4, §9).
- Long trips are testable: multi-day, multi-fuel-stop scenarios are in both §33 (unit tests) and §35 (demo scenarios).
- ELD derives from real events only: §17 mandates generation from backend event data, §22 mandates computed (never hard-coded) totals.
- Midnight boundaries are correct: §6 states midnight never resets HOS clocks; §20 defines the split precisely.
- Fuel/pickup/dropoff can satisfy the break requirement: §8 defines the qualifying-event rule and the no-redundant-break behavior explicitly.
- Cycle handling is honest given the input limitation: §4 forbids fabricating historical roll-off or auto-restarts; §24 defines BLOCKED as the honest alternative.
- Stops are placed on the actual route: §14 mandates geometry-based interpolation, never arbitrary city coordinates.
- The UI is specified as a real product, not a generic dashboard: §29 defines a specific, non-templated design system.
- Scope is realistic for 16 hours: §39's DO-NOT-BUILD list removes every high-risk, low-necessity feature; §40's implementation order front-loads the highest-risk logic (HOS engine, ELD renderer) and includes an explicit checkpoint.