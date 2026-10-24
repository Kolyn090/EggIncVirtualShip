# Maximum-crafts search mode

The search changes the strategies and objectives used to explore the existing
optimizer model. It does not change recipes, expected drops, starting inventory,
fuel costs or scheduling rules. Results concern the supplied recipes and known
wasmegg empirical means; even a model optimum would not guarantee actual game
drops.

## Modes and compatibility

- Direct CLI default: `--mode balanced`; the existing lexicographic order is
  crafts → launches → allocated fuel → completion → earlier starts.
- Runner configuration: `OPTIMIZATION_MODE="max-crafts"`. CLI scalar overrides
  still take precedence. Its existing 40-launch default is preserved; the
  requested benchmark explicitly overrides the cap to **360**.
- `max-crafts` spends its primary budget on improving feasible crafts and
  certificates, with no MILP launch/fuel/completion minimization. Its applied
  additional polishing allowance is zero even if `--polish-seconds` is set.
  A deterministic fixed-order calendar improvement is allowed only while time
  remains; it cannot lower crafts or change costs/drops.

Both paths use the existing supervised HiGHS/SciPy adapter and monotonic shared
wall-clock deadline. Process startup, serialization and native search consume
the allocated stage time. A killed native call remains uncertified, and its
last model-valid checkpoint or prior parent incumbent is retained. Python
imports, finishing aggregate construction, validation, cleanup and exports can
add overhead; this does not claim an exact whole-command runtime guarantee.

## Algorithms

### Integer resource bound

The existing compact resource relaxation has an integer variant with integer
mission counts for every usable `(ship,target,event multiplier)` option,
integer recipe crafts, and integer per-fuel allocation blocks. It preserves
starting inventory, recursive balances, target-dependent expected units, fuel
consumption, the combined budget, configured block size and total launch cap.
A daily cap supplies the safe aggregate bound `daily_cap * ceil(days)`.
Necessary service-window union cuts and total ship-hours also remain.

Only detailed scheduling is relaxed: there are no individual launch times,
slot assignment, exact daily placement, sleep/calendar precedence, or rolling
launch queues in this smaller model. Every real schedule projects into these
resource constraints, so a valid dual bound (or proved integer optimum) is a
valid global craft upper bound. An unproved resource incumbent is **not** an
upper bound, and its counts are **not** exported as a schedule.

The 30-day resource MIP has 512 variables and independently proves optimum
37. The balanced resource LP has a fractional bound about 37.936, whose valid
integer craft bound is also 37. Thus the integer model removes fractional
recipe/count/allocation solutions but **does not tighten the integer bound
below the previously reported 37 in this case**. Achievability of 37 still
requires a schedule.

### Validated alternative scheduling searches

The existing fast seed selects ingredient-leading options. Its restricted
optimum is only a feasible lower bound. Maximum-crafts search uses the resource
MIP's active options plus the seed's options to propose a first alternative
mix, then broadens to per-ingredient leaders by units per launch and units per
hour. Candidate searches use the **original full scheduling constraints**, with
unselected mission count/last-indicator columns fixed to zero. These zero
columns and only redundant satisfied zero rows are eliminated, producing small
matrix slices cached by option set. This is a restriction for finding witnesses,
not an alternative optimizer or a relaxation used to certify global bounds.

For the benchmark, the first candidate has about 1,541 variables for eight
options, compared with 45,281 variables for all 251 nondominated options. It can
mix low-fuel missions, different targets, repeated launches per slot, and
missions before/after the event. An aggregate candidate is accepted only when
rolling limits are already implied by duration/nonoverlap. It is lifted into
the complete original model, and actual launch times, events, slots, horizon,
blackouts, caps, integer crafts, inventory balances and allocated fuel are
independently validated before the craft lower bound changes.

When rolling limits require individual launches, the existing continuous-time
formulation remains in use, now with higher-craft cutoffs, integer resource
bounds, warm-started witnesses, refinement toward its full safe launch bound,
and explicitly scoped feasibility results. A restricted launch-cap failure
cannot certify infeasibility for the full problem.

### Adaptive feasibility and proof rules

Each attempt adds `target_crafts >= best_validated + 1` and still maximizes
crafts within that model. A `>=14` attempt can therefore jump straight to 30
or more; it need not solve one large MILP for 14, then 15, then 16. Candidate
model slices and incumbent values are reused, and a final unrestricted model
retains every nondominated ship/target option. Its remaining budget is reserved
for improving/proving the global result. The incumbent is retained between
stages and across failed attempts.

- **Feasible:** an independently validated witness meets the threshold. It
  updates the lower bound even if the solver timed out before proving optimality.
- **Proven infeasible:** a completed, unrestricted higher-count model is
  infeasible. With threshold `best+1`, this certifies the current craft maximum.
- **Unknown:** timeout, numerical rejection, or an infeasible restricted
  candidate/capped model. No global infeasibility cut is inferred.

A restricted model's optimal objective is never promoted to a global upper
bound. Full cutoff-model dual bounds are interpreted conservatively together
with the `threshold-1` region excluded by that cutoff. Matching a validated
craft lower bound and certified upper bound proves the maximum. Bounds are
checked for contradictions with the validated incumbent.

This reuses warm starts and cached matrix slices, **not persistent native
branch-and-bound state**. Supervised workers are deliberately isolated for safe
termination. Full native tree reuse across terminated calls is not implemented.

## Resume in balanced mode

```sh
./run_optimizer.sh --mode max-crafts --target ankh-4 --max-total-launches 360 \
  --solver-seconds 120 --polish-seconds 0 --output-dir results/ankh-max
./run_optimizer.sh --mode balanced --target ankh-4 --max-total-launches 360 \
  --incumbent-plan results/ankh-max --solver-seconds 30 --polish-seconds 120 \
  --output-dir results/ankh-balanced
```

The saved schedule/crafts are revalidated against current inputs, not trusted
because an old metadata file says “feasible.” Changed costs, inventory, target,
ship selection, event/sleep windows or caps can reject the plan. Compatible
witnesses are lifted into the current model or supplied to the timed model as
warm starts. Balanced mode cannot fall back to 13 if it has accepted a valid
30/35-craft incumbent. This does not guarantee that its secondary objectives
can be proved or improved within a short budget. Inventory is never updated
from planned launches or crafting.

A representative additional check resumed the validated 30-craft/360-launch
plan in balanced mode with only 5s + 2s. It retained 30 crafts and 435T allocation,
with all secondary guarantees still unproven. This demonstrates safe incumbent
reuse, not demonstrated convenience improvement.

## Benchmarks

The exact commands and raw per-stage data are stored in
[max_crafts.json](max_crafts.json), produced by:

```sh
.venv/bin/python benchmarks/max_crafts.py
# Individual cases can be selected without running the whole comparison:
.venv/bin/python benchmarks/max_crafts.py --cases max-crafts-30 max-crafts-120
```

All cases use `ankh-4`, 30 days, 500T combined fuel, three slots, one 48h 2×
event (days 14–16), sleep 00:00–11:00, per-slot rolling limit 2, total cap 360,
no daily cap, no extra no-launch interval, and the committed nonzero inventory.
All 533 usable profiles are enabled before exact dominance pruning to 251.
Balanced cases request the existing additional 2s polishing budget;
maximum-crafts cases also receive `--polish-seconds 2` but correctly apply zero
extra time. Measurements are single runs on this cloud environment, not a
speed or quality guarantee across hardware or separate time-limited runs.

| Mode | Primary seconds | Feasible new crafts | Proven integer upper bound | Launches | Allocated / consumed T | Completion day | External wall seconds | Maximum proven |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| balanced | 30 | 13 | 37 | 3 | 495 / 495.0 | 17.600 | 33.327 | No |
| max-crafts | 30 | 30 | 37 | 360 | 435 / 434.2 | 30.000 | 31.602 | No |
| balanced | 120 | 13 | 37 | 3 | 495 / 495.0 | 17.600 | 123.356 | No |
| max-crafts | 120 | 35 | 37 | 360 | 490 / 487.6 | 30.000 | 121.813 | No |
| balanced | 300 | 13 | 37 | 3 | 495 / 495.0 | 17.600 | 303.323 | No |
| max-crafts | 300 | 35 | 37 | 360 | 490 / 487.6 | 30.000 | 301.794 | No |

**Yes, more than 13 crafts were found:** the craft-focused mode found 30 in
30 seconds and 35 in both 120 and 300 seconds. The remaining certified interval
is **[35, 37]**, an integer-bound gap of **5.71%**. The 300-second run did not
improve the 120-second incumbent or prove that 36/37 are impossible. In
particular, a proved 35-craft optimum in an eight-option candidate model is
only a restricted-model result; it is not a proof of the full maximum.
Full `>=36` attempts ended unknown. No timeout was counted as infeasibility.

Balanced mode retained 13 in these three runs. Its integer-bound gap is
184.62%; its existing raw reported gap is 191.82%, using the fractional LP
bound before rounding. Craft-focused reporting uses the certified integer
bound directly. None of these runs proves secondary minima. The higher craft
count uses the full 360-launch allowance, with repeated low-fuel missions before
and after the event and mixed targeting, and finishes at the horizon. This is
an explicit search/convenience tradeoff under the configured cap, not a claim
that 360 launches are necessary for 35 crafts.

All six exported schedules were independently audited: actual durations,
per-slot overlap and rolling limits, total cap, event eligibility, sleep,
source CSV target-specific drop means, recipe consumption, starting stock,
nonnegative balances, consumed fuel and 5T allocation were recomputed from the
exports and current input data. All checks passed, and both modes' dashboards
were regenerated successfully from the final metadata. Existing inventory,
recipes, mission fuel data and expectation CSV bytes are unchanged.

Whole-command wall time exceeded the applied optimization allowance by roughly
1.3s for balanced cases and 1.6–1.8s for maximum-crafts cases in this batch.
The larger exported schedules require more validation/output work. Recorded
worker overruns remain measured rather than hidden; the shared monotonic budget
and solver termination logic are retained.

## Tests, files and limitations

The full Python suite passes **65 tests** and `npm test` passes **9 tests**.
New tests demonstrate a candidate improving a one-craft seed to three, correct
feasible/proven-infeasible/unknown classification, rejection of heuristic
incumbents as bounds, global-bound preservation after restricted infeasibility,
recovery of improved incumbents after later timeouts, integer resource bounds,
rolling/day/total caps, sleep/events, fuel blocks, resumed plans, and balanced
mode preservation. Existing real stalled-worker checkpoint/termination tests
continue to pass. Dashboard JavaScript tests verify the displayed bounds,
mode and nonmissing runtime budget, alongside existing checklist/progress tests.

Changed files:

- `optimize_reggference.py`: mode dispatch, integer resource variant, scheduling
  witness validation, higher-count timed searches, checkpoint loading and
  mode/runtime/search metadata.
- `max_crafts_search.py`: cached restricted model slices, adaptive cutoffs,
  incumbent retention and globally scoped proof logic on the existing model.
- `incumbent_plan.py`: strict CSV loading and current-constraint revalidation
  for cross-run feasible witnesses.
- `run_optimizer.sh`, `README.md`: mode configuration, CLI overrides and examples.
- `build_plan_dashboard.py`: prominent craft bounds, mode, time limit and runtime.
- `tests/test_max_crafts.py`, `tests/test_profiles.py`, `tests/test_runner.py`:
  new search, resume, mode and dashboard regressions.
- `benchmarks/max_crafts.py`, `max_crafts.json`, this report: exact commands,
  measured comparisons and remaining limitations.

The principal remaining limitation is proof of the full scheduling optimum.
Candidate sets broaden heuristically and are not exhaustive; the unrestricted
model remains expensive. Native tree state is not preserved between isolated
workers, and a longer separate run need not improve an incumbent. Use
`--incumbent-plan` to retain the best known compatible plan across runs.
Global bounds remain conditional on the supplied recipes and modeled empirical
means, including the previously documented custom ankh/titanium recipe mapping.
