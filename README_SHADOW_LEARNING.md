# V7.9 Shadow Learning

This branch adds an observational learner alongside the existing V7.9.2 application.

Safety boundary:
- Existing live scoring, signal-state transitions, alerts and trade selection are not modified.
- Shadow observations are written only to `shadow_candidates`.
- Directional candidates can be sampled while the live state is WATCHING or another non-entry state.
- Samples are throttled to one per direction every 15 minutes.
- Outcomes are resolved independently using 100-point target, 50-point stop and 480-minute horizon.
- Same-bar target+stop is marked ambiguous.
- Shadow results do not feed back into live thresholds or decisions.

The branch wrapper starts the existing `server:app` unchanged and adds the shadow observer as a separate startup worker.
