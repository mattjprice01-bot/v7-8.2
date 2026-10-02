# V7.9 learning integrity repair — 2 October 2026

The live performance API reported 27 entry-ready predictions: 9 targets,
18 stops, 33.3% target-before-stop win rate, 0 simulated R before costs,
and Brier 0.5347 versus a 0.25 fixed 50% benchmark. These historical totals
are not reliable validation: source inspection found entry-bar/duplicate
outcome risk and wall-clock timing during shadow replay. Full SQLite
contents were not accessible before deploying an audit route.

This patch ignores duplicate/out-of-order webhook timestamps, evaluates
prediction outcomes only on later 1-minute bars for the same symbol, and
excludes samples first observed beyond their horizon. Calibration now uses
only new version-2 barrier outcomes. Old predictions are retained, marked
legacy, and available in the audit; the validated dashboard starts at zero.

Shadow observations rebuild from saved snapshots into shadow_candidates_v2,
using payload ts (or historical received_at), with persisted replay and
per-symbol time checkpoints. Original shadow_candidates remains untouched.
Sampling is still once per 15 minutes per symbol/direction with 100-point
target, 50-point stop and 480-minute horizon. Replay is observational; it
does not generate alerts or change live trades. Saved historical context
may still contain source/data-quality flaws, and gaps within a horizon are
not reconstructed. Overlapping shadow samples are not independent trades.

/api/learning/audit returns bounded prediction and shadow evidence, source
snapshot counts and replay progress. Raw webhook bodies and keys are not
returned. Live snapshot results now include route-specific failed checks.
Entry thresholds and trading selection rules remain unchanged.

Validation: 23 tests pass, including replay timing, duplicate entry-bar
exclusion, symbol separation, horizon gaps, restart progress, preservation
of legacy records, new prediction versioning and audit secret exclusion.
Test environment used NumPy 2.2.6 after the latest wheel crashed at import;
production requirements were not changed.

Deployment requires explicit confirmation. Once deployed, retrieve audit
results, wait for replay checkpoint to catch up with snapshots, compare
legacy versus rebuilt shadow groups, and assess accepted/rejected setups
before any evidence-based entry-threshold tuning.
