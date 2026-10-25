# Async Booking — Retry & Request-Validity Plan

*High-level plan for team review. Edge / Ascend Scheduling Phase 2. Tracking: EDGE-460.*

## Summary

When Margo books an appointment, the request runs asynchronously. If the partner or integration is unavailable, the request is held and retried within a bounded **request-validity window** of **3 hours**. This plan unifies the retry behavior under one clock and makes every outcome visible to Platform.

## Background — how a booking flows today

```diagram
{
  "layout": "flow",
  "title": "How a booking flows today",
  "pipeline": [
    {"id": "platform", "label": "Platform"},
    {"id": "queue", "label": "Edge booking queue", "w": 330},
    {"id": "worker", "label": "Booking worker"}
  ],
  "branches": [
    {"label": "Agent healthy → book with the partner → report succeeded", "variant": "green"},
    {"label": "Permanent problem (slot taken, bad request) → report failed", "variant": "red"},
    {"label": "Agent not ready (inactive / maintenance) → hold the request → retry when healthy (≤ 3h)", "variant": "amber"},
    {"label": "Temporary partner glitch (timeout, rate-limit, brief outage) → quick retries → gives up", "variant": "red"}
  ]
}
```

| Situation | How long we keep trying | How it reports back |
| --- | --- | --- |
| Agent not ready | Up to **3 hours** | Held, then failed if the window expires |
| Temporary partner or infrastructure glitch | A few minutes | Not clearly reported today |

## The problem

1. **Inconsistent windows.** Temporary outages give up after minutes even though the booking remains valid for 3 hours.
2. **The window can quietly stretch.** Re-holding a request can reset its clock and let it live longer than intended.
3. **Silent give-ups.** A request can age out without Platform receiving a failure outcome.

## Proposed — one 3-hour request-validity window

```diagram
{
  "layout": "flow",
  "title": "Proposed — one 3-hour request-validity window",
  "pipeline": [
    {"id": "platform", "label": "Platform"},
    {"id": "queue", "label": "Edge booking queue", "w": 330},
    {"id": "worker", "label": "Booking worker"}
  ],
  "branches": [
    {"label": "Agent healthy → book with the partner → report succeeded", "variant": "green"},
    {"label": "Permanent problem → report failed with a clear reason", "variant": "red"},
    {"label": "Agent not ready OR temporary glitch → quick retries → hold until recovery → retry full flow", "variant": "amber", "h": 108},
    {"label": "Recovers within 3h → book → report succeeded", "variant": "green"},
    {"label": "3h window crossed → stop → report failed (request-validity window crossed)", "variant": "red"}
  ]
}
```

The request carries one absolute deadline from arrival time plus 3 hours. The deadline is never reset. Temporary failures are held rather than dropped, recovery replays the normal booking flow, and expiry always reports a `failed` outcome with a clear reason.

## What Platform sees

- **`succeeded`** — booked; includes appointment details.
- **`parked`** — held for a temporarily unavailable agent or partner; will be retried.
- **`failed`** — will not be booked; includes a reason such as slot taken or request-validity window crossed.

## Benefits

- **One consistent 3-hour promise** for both agent unavailability and temporary partner glitches.
- **No lost bookings inside the window**, and no bookings that outlive it.
- **Full visibility** for every success, hold, and give-up.
- **Kind to partners** — retry when they recover, not on a blind timer.
