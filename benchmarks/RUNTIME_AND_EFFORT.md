# Runtime budgets and launch effort

This report supersedes the runtime and fuel-accounting limitations in the
previous wasmegg report. All measurements below use the existing expected-drop
model and supplied recipes; they are not guarantees of actual game drops.

## Runtime investigation

There were several distinct sources of excess time:

1. Input/aggregate construction was outside the primary budget. Stage deadlines
   were calculated from different start points, secondary code created fresh
   allowances, and expired calls were clamped to a positive 0.001 seconds.
2. The native HiGHS `time_limit` is a soft solver limit. Some presolve and native
   optimization operations do not check it promptly. Passing a smaller limit
   to the next call does not interrupt the current one.
3. Native model conversion, warm-start installation, validation and output add
   time beyond the native solver timer. Python aggregate construction was also
   slow because of repeated pandas lookups and individual sparse assignments.

A reproduction at pre-change commit `dc71d36`, with all ships/targets, 30 days,
ankh crafting, 500T, sleep 00:00–11:00, one 48-hour event, and budgets **5 + 2
seconds**, took **13.63 seconds externally**. Aggregate construction took 3.154s.
The seed requested 1.000s and took 1.972s; full craft search requested 3.022s and
took 5.297s. Full search had presolve disabled, so presolve alone cannot explain
the overruns. The earlier documented 39-second case similarly spent 35.738s in
a full-model call requesting 4.307s. These are native-call overruns, not simply
slow HTML generation. See [raw baseline measurements](runtime_before.json).

The new 30-second run measured about 0.11s for native model setup, with most
primary time inside `Highs.run()`. Telemetry identifies startup/serialization,
native setup, or native solve when a worker is killed. Completed native calls
also report HiGHS' own runtime. For killed calls, `native_run_seconds` is an
estimate from worker entry to parent inspection, including small reaping
latency; it is not fabricated native CPU timing. Presolve versus branch-and-
bound time is not individually available from these aggregate timing fields.
`--verbose-solver` retains native solver logs when deeper inspection is needed.

## Budget contract and worker safety

`--solver-seconds S` establishes a monotonic deadline at entry to `solve`, before
input/model construction. Construction, seeding, bound calculation and primary
search share it. Secondary objectives can use unused primary time plus
`--polish-seconds P`. The total optimization deadline is the original start
plus **S + P**; it is never reset. `P` defaults to 10, and `P=0` adds no extra
allowance rather than disabling secondary optimization. No new solver or final
calendar-optimization stage starts after its allocated deadline.

Every call checks `time.monotonic()` before dispatch and passes only its
remaining allocation. Native calls execute in a separate worker. Safe
`forkserver` processes are used where available, with `spawn` as the fallback;
plain `fork` does not inherit potentially active native solver threads. Worker
startup, serialization, model conversion, warm starts, presolve and search all
consume that stage's wall-clock allowance. The worker checks again before
native search and forwards the remaining time as HiGHS' soft `time_limit`.

The parent independently supervises the deadline and kills a worker that has
not finished. Native improving-solution callbacks write atomic temporary
checkpoints. Before accepting a checkpoint the parent checks every original
row, variable bound and integrality condition. The previously validated
incumbent stays in the parent between calls and is retained if the checkpoint
is absent, invalid or worse. A killed solve is always reported as time limited,
never optimal. SciPy fallback solves are supervised too, but cannot expose
intermediate MIP solutions; they retain previously completed incumbents.

**This is not an exact real-time guarantee for the complete Python command.**
Imports happen before `solve`; OS scheduling/worker reaping, validation,
finishing parent aggregate construction, cleanup and CSV/HTML export add
measured overhead. Timed-model construction checks its deadline periodically
and aborts unfinished refinements safely. A very large aggregate construction
may itself finish after the deadline, after which solves are skipped. Worker
termination also depends on OS process scheduling. A caller requiring a hard
external cutoff should retain its own process/container supervisor and allow
for export overhead; killing the whole command may prevent final exports.

`[Runtime]` and `optimization.timing` report model construction, primary search,
launch-count, fuel and completion optimization, other secondary time, total
elapsed time, worker terminations and whether any call exceeded its requested
allocation by more than 20ms. Individual calls include requested/actual time,
setup/run telemetry and proof/bound data. Total elapsed in this JSON measures
`solve` through export; the benchmark's external wall clock additionally
includes Python imports and interpreter shutdown. Small process-reaping
overshoots are reported, not hidden.

## Why the old plan used 250 launches

Fuel minimization previously preceded launch effort. After fixing six crafts,
the model could prefer hundreds of low-tier drops at zero modeled fuel over a
few higher-capacity missions. Launch count was only the last tie-breaker and
usually received no useful solver time. This was a consequence of the chosen
objective order, not evidence that the 6-craft incumbent was a maximum.

The pinned wasmegg `MissionType.virtueFuels` confirms that Heavy missions use
Humility only: short Heavy consumes 50 million Humility eggs, has boosted
capacity 22, and lasts 0.75h at configured research. Humility is outside this
project's four-fuel T budget, matching wasmegg's existing accounting. Those
missions remain zero on the modeled axes, and remain selectable. No penalty
fuel values or ship exclusions were invented. Their empirical loot means are
calculated by the same original histogram/supply functions as other missions;
low-tier material supply is useful through recursive crafting.

**BCR was incorrectly recorded as free.** Source short BCR uses 100 million
Humility plus 10 million Integrity eggs: **0.00001T Integrity**. Standard and
extended use 0.00002T and 0.00003T. These explicit source costs replace the
three zero CSV entries. Any positive Integrity usage must still be allocated
in 5T blocks, so its allocation impact is greater than its consumed amount.
The same audit found three other source mismatches, corrected directly:

| Mission | Previous fuel T (Curiosity, Kindness, Resilience) | Source values |
| --- | --- | --- |
| henliner-1 | 20, 25, 20 | 25, 20, 0 |
| voyegger-3 | 15, 25, 15 | 25, 15, 0 |
| defihent-3 | 3, 3, 3 | 3, 3, 0 |

The source is pinned shared commit `8a9e04d299dba00af4b34ddf46241665fee30044`.
A Node regression test checks all repeatable mission fuel rows against
`virtueFuels`, including unit conversion by 10^12. Actual inventory, supplied
recipes, generated expectations, and wasmegg source files are unchanged.

## Caps and priorities

Both direct CLI caps default to zero (unlimited):

```sh
./run_optimizer.sh --max-total-launches 40 --max-launches-per-day 3
./run_optimizer.sh --max-total-launches 0 --max-launches-per-day 0
```

The runner defaults to `MAX_TOTAL_LAUNCHES=40`, `MAX_LAUNCHES_PER_DAY=0`;
explicit CLI overrides win. Total launches include every slot and event status.
Daily launches are counted across all slots in half-open planning-day buckets
`[24d,24(d+1))`. This is separate from the existing per-slot rolling-hour rule;
exactly hour 24 starts a new day. Returns do not count.

Aggregate models constrain sums of launch-count variables. Individual-launch
models constrain selected launch/phase variables, and the total cap tightens
the safe launch-variable bound. A daily cap splits phases at day boundaries.
The same constraints apply to primary/seed and all secondary models. Export
and dashboard validators independently check actual launch timestamps. Final
fixed-order calendar optimization preserves original daily assignments when a
daily cap is active. Caps never depend on deleting or shifting exported rows.
The existing surplus-work cleanup remains an additional correctness-preserving
cleanup, not the mechanism enforcing either cap.

Lexicographic order is now:

1. Maximize target crafts, preserving the best validated feasible craft count.
2. Fix that count and minimize total launches.
3. Preserve crafts/launches and minimize allocated fuel in configured blocks.
4. Preserve those values and minimize actual last-mission completion time.
5. Prefer earlier launches as a final tie-breaker.

Each later model locks the best feasible attained values. No weighted tradeoff
can lower crafts to improve effort, or increase launches to save fuel. If a
stage times out, lower priorities remain conditional on its unproved attained
value. Metadata and dashboard distinguish craft, launch, fuel and completion
proofs; even zero fuel is not presented as a global lexicographic certificate
if minimum launch count is unproved. A capped scheduling subproblem's local
proof remains distinct from a full-model proof.

## Gap and formulation investigation

A bound of 45 and feasible value 6 gives `(45-6)/6 = 650%`; it is not proof
that six is optimal. Two mechanisms contributed: weak/unfinished upper bounds
and poor feasible search in a large symmetric ship/target formulation. The
full 30-day model retains 251 nondominated options from 533 usable profiles,
with 45,281 variables and over 23,000 rows. Repeated target profiles multiply
slot/phase choices. Fractional last-mission indicators weaken scheduling LP
bounds; count-order symmetry and native root work make proofs expensive.

The independent resource relaxation has only **512 continuous variables**,
no slot binaries and **no Big-M constraints**, yet still bounds the unlimited
case at about **44.186 crafts**. Therefore Big-M scheduling is not the sole
cause of the large gap: relaxing integer recipes/counts/allocation and detailed
scheduling also leaves a substantial gap. We cannot identify one mechanism as
uniquely dominant without stronger certificates; the full maximum remains
unproved. The previous all-option seed often failed to improve zero in short
runs. A small ingredient-leading seed now finds **13 feasible crafts** quickly;
its restricted optimum is never used as a global upper bound. All nondominated
choices remain in the subsequent full search.

New valid service-window cuts strengthen both actual formulations. For each
bonus class and three duration thresholds (minimum, middle, maximum), take
the union of `[launch_phase_start, min(horizon, phase_end + threshold)]`.
Every mission in the selected duration subset must fly entirely in that union.
Per-slot nonoverlap therefore bounds its total service hours by the union's
length (or slots times that length in the compact relaxation/timed model).
This limits fractional capacity spread across many sleep/event phases while
retaining every feasible integer schedule and every useful ship-target option.
The compact resource LP provides fast, separately scoped bounds. Pareto
pruning uses the identical exact comparison in NumPy, and sparse matrices are
constructed in batches rather than one cell at a time.

## Benchmarks

All new cases use **all ships and targeting options**, `ankh-4`, 30 days, 500T,
three slots, the committed nonzero `data/inventory.csv`, one 48h 2× event,
sleep 00:00–11:00, per-slot rolling limit 2, and an additional 2s polishing
budget. No extra no-launch interval is configured. These are the original
unlimited scenario and requested capped scenarios under the new implementation;
the baseline above is an additional before-code runtime reproduction. Costs,
seeding and objectives all changed, so before/after craft improvements cannot
be attributed to one change alone.

| Case | Budget S + P | Feasible crafts | Integer craft bound | Launches | Allocated / consumed T | Completion day | External wall s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| unlimited-5 | 5 + 2 | 13 | 44 | 3 | 495 / 495 | 17.600 | 8.334 |
| unlimited-30 | 30 + 2 | 13 | 44 | 3 | 495 / 495 | 17.600 | 33.159 |
| unlimited-120 | 120 + 2 | 13 | 44 | 3 | 495 / 495 | 17.600 | 123.212 |
| cap20-30 | 30 + 2 | 13 | 24 | 3 | 495 / 495 | 17.600 | 33.454 |
| cap40-30 | 30 + 2 | 13 | 26 | 3 | 495 / 495 | 17.600 | 33.249 |
| cap60-30 | 30 + 2 | 13 | 28 | 3 | 495 / 495 | 17.600 | 33.810 |
| daily3-cap40-30 | 30 + 2 | 13 | 26 | 3 | 495 / 495 | 17.058 | 33.210 |

All seven runs retain feasible plans; **none proves the craft maximum, minimum
launch count, minimum allocated fuel, or global minimum completion time**.
The new representative plan is three event-boosted extended Henliners, mixing
ankh and meteorite targeting, rather than hundreds of free missions. Long waits
for the days 14–16 event remain; some launches are still later within that event
than necessary because completion improvement timed out. No global timing
optimum is claimed. More solver time does not currently guarantee a stronger
incumbent or proof.

Reported relative gaps use the continuous dual bound (about 239.89% unlimited,
86.83% with cap 20, 107.49% with cap 40, 121.21% with cap 60); the craft-bound
column floors that bound because crafts are integral. It therefore supports
a slightly tighter integer gap than the raw solver/relaxation gap shown.

The 30s unlimited case breaks down as follows:

| Component | Seconds |
| --- | ---: |
| Model construction (including input/profile setup) | 1.497 |
| Primary optimization | 28.541 |
| Launch minimization | 0.890 |
| Fuel minimization | 0.476 |
| Completion minimization | 0.457 |
| Other secondary objectives | 0.045 |
| Total inside solve through exports | 32.317 |

Calls can exceed their stage allocation slightly during process reaping and
validation; the 30s full search exceeded its allocation by about 23ms and was
terminated in `highs_run`. Six of the seven cases flagged at least one >20ms
overshoot; the 5s case did not. No worker was allowed to continue for tens of
seconds past its deadline. Total command overhead above S+P was approximately
1.16–1.81s here, including imports, exports and shutdown; this is measured
overhead, not a universal bound. The cap-60 run had unusually slower input/model
setup; actual construction time is included in its budget.

Raw per-call timing, bounds and proof statuses are in
[runtime_and_effort.json](runtime_and_effort.json). Reproduce with:

```sh
.venv/bin/python benchmarks/runtime_and_effort.py
# Or select cases:
.venv/bin/python benchmarks/runtime_and_effort.py --cases unlimited-5 cap40-30
```

The driver prints/stores each exact CLI command, clears old result metadata,
and applies an external safety timeout so it never reads stale results.

## Tests and changed files

`python -m unittest discover -s tests -v` passes **56 tests**; `npm test` passes
**9 tests**. New tests cover stalled-worker termination, checkpoint validation
and preservation, expired-stage skipping, remaining-time clamping, supervised
SciPy fallback, total and daily caps in both formulations, day boundaries,
free ships, launch-first priorities without craft loss, source fuel values,
resource bounds, dashboard metadata and runner overrides. Existing inventory,
targeting, event, sleep, fuel-block, per-slot rolling-rate, export and checklist
regressions continue to pass. A scheduling test deliberately changes its
expected outcome: launch-first priority uses four boosted missions instead of
a larger mix of ordinary/boosted missions, so completion moves from hour 3 to
hour 4 while crafts stay equal. This follows the requested priority order.

- `solver_backend.py`: supervised worker execution, atomic incumbent checkpoints,
  full-model validation and native timing telemetry.
- `optimize_reggference.py`: monotonic shared budgets, stage reporting, exact
  launch/day caps, launch-first secondary objectives, resource bounds/cuts and
  focused feasible seeding.
- `mission_profiles.py`: vectorized exact dominance comparisons.
- `data/mission.csv`: six source-confirmed fuel corrections.
- `schedule_validation.py`, `build_plan_dashboard.py`: actual timestamp cap
  validation and launch-cap/proof display.
- `run_optimizer.sh`, `README.md`, `docs/WASMEGG_EXPECTATIONS.md`: configuration,
  examples, budget semantics and correction links.
- `tests/test_runtime_limits.py`, `tests/test_launch_effort.py`, existing solver,
  schedule, runner and Node tests: meaningful regressions.
- This report, benchmark script and JSON measurements: reproducibility evidence.
